"""
tidemark.store.credentials
──────────────────────────
Credential storage.

Two backends:

- ``KeyringStore`` — uses ``keyring`` (Secret Service on Linux, Keychain on
  macOS, Credential Manager on Windows). Tried first unless overridden.
- ``EncryptedFileStore`` — Fernet-encrypted JSON at
  ``<config_dir>/credentials.enc`` (mode 0600), key derived via scrypt.

The chosen backend is recorded in ``settings["credential_store.backend"]``
the first time a store is opened successfully. **It is never changed
silently.** If the configured backend is ``keyring`` and the probe fails
(no desktop session, no Secret Service, etc.), ``CredentialStoreUnavailable``
is raised with exact remedies. There is no automatic fallback to the file
store: falling back would open an *empty* file store and later fail with a
confusing "no credentials" error.
"""

from __future__ import annotations

import base64
import fcntl
import json
import logging
import os
import struct
import threading
import uuid
from pathlib import Path
from typing import Protocol

import keyring
from cryptography.fernet import Fernet, InvalidToken
from cryptography.hazmat.primitives.kdf.scrypt import Scrypt

from tidemark.store.db import Database
from tidemark.store.repositories import SettingsRepo

logger = logging.getLogger(__name__)


# ── Public exceptions ───────────────────────────────────────────────────────

class CredentialStoreError(RuntimeError):
    """Base class."""


class CredentialStoreUnavailable(CredentialStoreError):
    """Raised when the configured store cannot be used."""


class CredentialNotFound(CredentialStoreError):
    """Raised when a requested credential ref does not exist."""


class WrongPassphrase(CredentialStoreError):
    """Raised when the file store cannot decrypt with the supplied passphrase."""


# ── Protocol and payloads ──────────────────────────────────────────────────

class CredentialStore(Protocol):
    kind: str

    def get(self, ref: str) -> tuple[str, str]:
        """Return ``(username, password)`` for ``ref``."""

    def set(self, ref: str, username: str, password: str) -> None: ...

    def delete(self, ref: str) -> None: ...


# ── Passphrase providers ───────────────────────────────────────────────────

class PassphraseProvider(Protocol):
    def __call__(self) -> str: ...


class InteractivePassphraseProvider:
    """Prompt on the terminal. M2 primary for CLI interactive use."""

    def __init__(self, prompt: str = "Tidemark credential passphrase: ") -> None:
        self._prompt = prompt

    def __call__(self) -> str:
        import getpass
        return getpass.getpass(self._prompt)


class FilePassphraseProvider:
    """Read the passphrase from a mode-0600 file."""

    def __init__(self, path: Path) -> None:
        self._path = Path(path)

    def __call__(self) -> str:
        stat = self._path.stat()
        if stat.st_mode & 0o077:
            raise CredentialStoreError(
                f"passphrase file {self._path} has permissions "
                f"{oct(stat.st_mode & 0o777)}; must be 0600"
            )
        return self._path.read_text(encoding="utf-8").rstrip("\n")


class StaticPassphraseProvider:
    """Fixed passphrase. For tests only."""

    def __init__(self, value: str) -> None:
        self._value = value

    def __call__(self) -> str:
        return self._value


# ── Keyring backend ────────────────────────────────────────────────────────

_KEYRING_SERVICE = "tidemark"


class KeyringStore:
    kind = "keyring"

    def get(self, ref: str) -> tuple[str, str]:
        blob = keyring.get_password(_KEYRING_SERVICE, ref)
        if not blob:
            raise CredentialNotFound(f"credential ref {ref!r} not found in keyring")
        data = json.loads(blob)
        return data["username"], data["password"]

    def set(self, ref: str, username: str, password: str) -> None:
        keyring.set_password(
            _KEYRING_SERVICE, ref,
            json.dumps({"username": username, "password": password}),
        )

    def delete(self, ref: str) -> None:
        try:
            keyring.delete_password(_KEYRING_SERVICE, ref)
        except keyring.errors.PasswordDeleteError:
            pass


def probe_keyring(timeout: float = 5.0) -> tuple[bool, str]:
    """Return ``(usable, reason)``. Runs the probe in a worker thread with a
    timeout so a hanging keyring cannot hang CLI startup."""
    result: dict[str, object] = {}

    def _run() -> None:
        try:
            backend = keyring.get_keyring()
            name = f"{type(backend).__module__}.{type(backend).__name__}"
            if "fail" in name.lower() or "null" in name.lower():
                result["ok"] = False
                result["reason"] = f"keyring backend is {name}"
                return
            probe_ref = f"probe-{uuid.uuid4()}"
            payload = "1"
            try:
                keyring.set_password(_KEYRING_SERVICE, probe_ref, payload)
                got = keyring.get_password(_KEYRING_SERVICE, probe_ref)
                if got != payload:
                    result["ok"] = False
                    result["reason"] = "keyring round-trip returned wrong value"
                    return
                result["ok"] = True
                result["reason"] = f"keyring backend is {name}"
            finally:
                try:
                    keyring.delete_password(_KEYRING_SERVICE, probe_ref)
                except Exception:
                    pass
        except Exception as exc:  # noqa: BLE001
            result["ok"] = False
            result["reason"] = f"keyring error: {exc}"

    t = threading.Thread(target=_run, daemon=True)
    t.start()
    t.join(timeout)
    if t.is_alive():
        return False, f"keyring probe timed out after {timeout}s"
    return bool(result.get("ok", False)), str(result.get("reason", "unknown"))


# ── File backend ───────────────────────────────────────────────────────────

_MAGIC = b"TIDEMARK2"
_VERSION = 2
_KDF = b"scrypt"
_N_LOG2 = 17
_R = 8
_P = 1
_SALT_LEN = 16


class EncryptedFileStore:
    kind = "file"

    def __init__(self, path: Path, passphrase_provider: PassphraseProvider) -> None:
        self._path = Path(path)
        self._passphrase_provider = passphrase_provider
        self._path.parent.mkdir(parents=True, exist_ok=True)

    def _derive_key(self, salt: bytes) -> bytes:
        kdf = Scrypt(salt=salt, length=32, n=2 ** _N_LOG2, r=_R, p=_P)
        raw = kdf.derive(self._passphrase_provider().encode("utf-8"))
        # Fernet expects URL-safe base64 of exactly 32 bytes.
        return base64.urlsafe_b64encode(raw)

    def _read_payload(self) -> dict:
        if not self._path.exists():
            return {"version": _VERSION, "credentials": {}}
        with self._path.open("rb") as fh:
            magic = fh.read(len(_MAGIC))
            if magic != _MAGIC:
                raise CredentialStoreError(
                    f"{self._path} has unknown magic {magic!r}; "
                    f"refusing to read (may be a different version)"
                )
            version = fh.read(1)[0]
            if version != _VERSION:
                raise CredentialStoreError(
                    f"{self._path} has unknown version {version}; expected {_VERSION}"
                )
            kdf = fh.read(6).rstrip(b"\x00")
            if kdf != _KDF:
                raise CredentialStoreError(f"unsupported KDF {kdf!r}")
            n_log2 = fh.read(1)[0]
            r = fh.read(1)[0]
            p = fh.read(1)[0]
            if (n_log2, r, p) != (_N_LOG2, _R, _P):
                raise CredentialStoreError(
                    f"unsupported KDF params n_log2={n_log2} r={r} p={p}"
                )
            salt = fh.read(_SALT_LEN)
            token_len = struct.unpack(">I", fh.read(4))[0]
            token = fh.read(token_len)

        key = self._derive_key(salt)
        try:
            plaintext = Fernet(key).decrypt(token)
        except InvalidToken as exc:
            raise WrongPassphrase(
                "cannot decrypt credential file with supplied passphrase"
            ) from exc
        return json.loads(plaintext.decode("utf-8"))

    def _write_payload(self, payload: dict) -> None:
        salt = os.urandom(_SALT_LEN)
        key = self._derive_key(salt)
        token = Fernet(key).encrypt(json.dumps(payload).encode("utf-8"))
        header = (
            _MAGIC
            + bytes([_VERSION])
            + _KDF.ljust(6, b"\x00")
            + bytes([_N_LOG2, _R, _P])
            + salt
            + struct.pack(">I", len(token))
        )
        tmp = self._path.with_name(f".{self._path.name}.{uuid.uuid4().hex}.tmp")
        try:
            fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            try:
                os.write(fd, header + token)
                os.fsync(fd)
            finally:
                os.close(fd)
            os.replace(tmp, self._path)
            dfd = os.open(self._path.parent, os.O_RDONLY)
            try:
                os.fsync(dfd)
            finally:
                os.close(dfd)
        finally:
            if tmp.exists():
                tmp.unlink(missing_ok=True)

    def _locked_write(self, payload: dict) -> None:
        lock = self._path.with_suffix(self._path.suffix + ".lock")
        lock.touch(exist_ok=True)
        with lock.open("rb") as fh:
            fcntl.flock(fh.fileno(), fcntl.LOCK_EX)
            try:
                self._write_payload(payload)
            finally:
                fcntl.flock(fh.fileno(), fcntl.LOCK_UN)

    def get(self, ref: str) -> tuple[str, str]:
        payload = self._read_payload()
        try:
            entry = payload["credentials"][ref]
        except KeyError as exc:
            raise CredentialNotFound(
                f"credential ref {ref!r} not found in {self._path}"
            ) from exc
        return entry["username"], entry["password"]

    def set(self, ref: str, username: str, password: str) -> None:
        payload = self._read_payload()
        payload["credentials"][ref] = {"username": username, "password": password}
        self._locked_write(payload)

    def delete(self, ref: str) -> None:
        payload = self._read_payload()
        payload["credentials"].pop(ref, None)
        self._locked_write(payload)

    def rekey(self, old: PassphraseProvider, new: PassphraseProvider) -> None:
        """Re-encrypt the file with a new passphrase."""
        old_provider, self._passphrase_provider = self._passphrase_provider, old
        try:
            payload = self._read_payload()
        finally:
            self._passphrase_provider = old_provider
        self._passphrase_provider = new
        self._locked_write(payload)


# ── Factory ────────────────────────────────────────────────────────────────

_BACKEND_KEY = "credential_store.backend"
FILE_NAME = "credentials.enc"


class CredentialStoreFactory:
    """Open the configured credential store.

    Selection is **sticky**: the backend chosen on first successful open is
    recorded in ``settings`` and reused. An explicit
    ``TIDEMARK_CREDENTIAL_STORE=file|keyring`` env var overrides the setting
    for the current process only and is reported by ``credentials status``.
    """

    def __init__(self, config_dir: Path, db: Database) -> None:
        self._config_dir = config_dir
        self._db = db
        self._settings = SettingsRepo(db)

    def open(
        self,
        *,
        passphrase_provider: PassphraseProvider | None = None,
    ) -> CredentialStore:
        env_override = os.getenv("TIDEMARK_CREDENTIAL_STORE", "").strip().lower()
        configured = self._settings.get(_BACKEND_KEY) or "unset"

        if env_override in ("file", "keyring"):
            target = env_override
        elif configured == "unset":
            target = "keyring"
        else:
            target = configured

        if target == "keyring":
            usable, reason = probe_keyring()
            if not usable:
                raise CredentialStoreUnavailable(
                    f"configured backend is 'keyring' but no usable keyring "
                    f"is available in this process ({reason}).\n\n"
                    "Two ways forward:\n\n"
                    "  1. Run this command from an interactive desktop "
                    "session, which has access to the keyring.\n\n"
                    "  2. If you want the daemon or cron to use file-based "
                    "credentials instead, migrate them now:\n"
                    "       tidemark credentials set-backend file\n"
                    "       tidemark credentials migrate-keyring-to-file\n\n"
                    "The configured backend has NOT been changed."
                )
            store = KeyringStore()
            if configured == "unset":
                self._settings.set(_BACKEND_KEY, "keyring")
            return store

        if passphrase_provider is None:
            raise CredentialStoreUnavailable(
                "credential store is 'file' but no passphrase provider was "
                "supplied. Set TIDEMARK_PASSPHRASE_FILE or "
                "TIDEMARK_PASSPHRASE, or run interactively."
            )
        store = EncryptedFileStore(self._config_dir / FILE_NAME, passphrase_provider)
        if configured == "unset":
            self._settings.set(_BACKEND_KEY, "file")
        return store

    def get_configured_backend(self) -> str:
        return self._settings.get(_BACKEND_KEY) or "unset"

    def set_backend(self, backend: str) -> None:
        if backend not in ("keyring", "file"):
            raise ValueError("backend must be 'keyring' or 'file'")
        self._settings.set(_BACKEND_KEY, backend)


def passphrase_provider_from_env() -> PassphraseProvider | None:
    """Return a passphrase provider based on env vars, if any are set."""
    path = os.getenv("TIDEMARK_PASSPHRASE_FILE")
    if path:
        return FilePassphraseProvider(Path(path))
    if os.getenv("TIDEMARK_PASSPHRASE"):
        logger.warning(
            "TIDEMARK_PASSPHRASE is visible via 'ps e'; prefer "
            "TIDEMARK_PASSPHRASE_FILE for anything beyond a one-off test"
        )
        return StaticPassphraseProvider(os.environ["TIDEMARK_PASSPHRASE"])
    return None
