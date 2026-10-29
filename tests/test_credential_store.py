"""Credential store — file round-trip, sticky backend, no silent fallback."""

from __future__ import annotations

from pathlib import Path

import pytest

from tidemark.store.credentials import (
    CredentialNotFound,
    CredentialStoreFactory,
    CredentialStoreUnavailable,
    EncryptedFileStore,
    StaticPassphraseProvider,
    WrongPassphrase,
)
from tidemark.store.db import Database, migrate


def _factory(tmp_path: Path) -> tuple[CredentialStoreFactory, Database]:
    db = Database(tmp_path / "t.db")
    migrate(db)
    return CredentialStoreFactory(tmp_path / "cfg", db), db


def test_file_store_roundtrip(tmp_path: Path) -> None:
    store = EncryptedFileStore(
        tmp_path / "creds.enc", StaticPassphraseProvider("passphrase")
    )
    store.set("default", "alice", "s3cret")
    assert store.get("default") == ("alice", "s3cret")
    assert oct((tmp_path / "creds.enc").stat().st_mode & 0o777) == "0o600"


def test_file_store_wrong_passphrase(tmp_path: Path) -> None:
    store = EncryptedFileStore(
        tmp_path / "creds.enc", StaticPassphraseProvider("correct")
    )
    store.set("default", "alice", "s3cret")
    wrong = EncryptedFileStore(
        tmp_path / "creds.enc", StaticPassphraseProvider("wrong")
    )
    with pytest.raises(WrongPassphrase):
        wrong.get("default")


def test_file_store_missing_ref(tmp_path: Path) -> None:
    store = EncryptedFileStore(
        tmp_path / "creds.enc", StaticPassphraseProvider("p")
    )
    with pytest.raises(CredentialNotFound):
        store.get("nope")


def test_factory_raises_when_keyring_unusable_and_no_passphrase(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Backend unset -> defaults to keyring; if keyring unusable and no
    passphrase provider, opening must raise rather than silently creating an
    empty file store. probe_keyring is forced to fail so the test is
    deterministic regardless of the developer's desktop session."""
    monkeypatch.delenv("TIDEMARK_CREDENTIAL_STORE", raising=False)
    monkeypatch.delenv("TIDEMARK_PASSPHRASE_FILE", raising=False)
    monkeypatch.delenv("TIDEMARK_PASSPHRASE", raising=False)
    monkeypatch.setattr(
        "tidemark.store.credentials.probe_keyring",
        lambda *a, **k: (False, "simulated"),
    )
    factory, db = _factory(tmp_path)
    with pytest.raises(CredentialStoreUnavailable):
        factory.open()
    db.close()


def test_factory_no_silent_fallback_from_keyring(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Backend=keyring, probe fails -> CredentialStoreUnavailable, setting unchanged, no file created."""
    monkeypatch.delenv("TIDEMARK_CREDENTIAL_STORE", raising=False)
    monkeypatch.setattr(
        "tidemark.store.credentials.probe_keyring",
        lambda *a, **k: (False, "simulated"),
    )
    factory, db = _factory(tmp_path)
    factory.set_backend("keyring")

    with pytest.raises(CredentialStoreUnavailable) as excinfo:
        factory.open()
    assert "keyring" in str(excinfo.value)
    assert "migrate-keyring-to-file" in str(excinfo.value)
    assert factory.get_configured_backend() == "keyring"
    assert not (tmp_path / "cfg" / "credentials.enc").exists()
    db.close()


def test_env_override_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TIDEMARK_CREDENTIAL_STORE", "file")
    factory, db = _factory(tmp_path)
    store = factory.open(passphrase_provider=StaticPassphraseProvider("p"))
    store.set("default", "u", "p")
    assert store.get("default") == ("u", "p")
    db.close()
