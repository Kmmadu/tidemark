"""
tidemark.store.git_repo
───────────────────────
The configs git repository.

Layout::

    configs/<device>/running.cfg                       stable file per device
    configs/pre_restore/<device>/<YYYY>/<MM>/<sha>.cfg content-addressed

A "normal" snapshot overwrites ``<device>/running.cfg`` and commits only
when the content changes. A "pre_restore" snapshot is content-addressed and
always committed (each pre-restore is its own recovery point).

``read_at(commit_sha, rel_path)`` reads a file **from the git object store**
so restore uses the exact committed bytes, not the current working tree.

A cross-process file lock on ``.lock`` serialises writes; concurrent
``store`` calls from ``run_many`` therefore cannot collide on
``.git/index.lock``.
"""

from __future__ import annotations

import fcntl
import logging
import re
import shutil
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path

from git import InvalidGitRepositoryError, Repo

logger = logging.getLogger(__name__)

_AUTHOR_NAME = "tidemark"
_AUTHOR_EMAIL = "tidemark@localhost"
_NAME_RE = re.compile(r"^[A-Za-z0-9._-]+$")

NORMAL_REL = "running.cfg"


class ConfigRepoError(RuntimeError):
    """Base class for ConfigRepo errors."""


class InvalidDeviceNameError(ConfigRepoError):
    """Raised when a device name fails ``^[A-Za-z0-9._-]+$``."""


class ConfigRepoLockError(ConfigRepoError):
    """Raised when the repo lock cannot be acquired within the timeout."""


def _validate_name(name: str) -> None:
    if not name or not _NAME_RE.match(name):
        raise InvalidDeviceNameError(
            f"invalid device name {name!r}; must match ^[A-Za-z0-9._-]+$"
        )


class ConfigRepo:
    """Git-backed storage of normal and pre-restore snapshots."""

    def __init__(self, root: Path, *, lock_timeout: float = 30.0) -> None:
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        self._lock_path = self.root / ".lock"
        self._lock_timeout = lock_timeout
        try:
            self._repo = Repo(self.root)
        except (InvalidGitRepositoryError, Exception):
            self._repo = Repo.init(self.root)
            with self._repo.config_writer() as cfg:
                cfg.set_value("user", "name", _AUTHOR_NAME)
                cfg.set_value("user", "email", _AUTHOR_EMAIL)

    # ── Locking ────────────────────────────────────────────────────────────

    @contextmanager
    def _locked(self) -> Iterator[None]:
        self._lock_path.touch(exist_ok=True)
        with self._lock_path.open("rb") as fh:
            try:
                fcntl.flock(fh.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                # Blocking retry with a simple deadline.
                import time
                deadline = time.monotonic() + self._lock_timeout
                while time.monotonic() < deadline:
                    try:
                        fcntl.flock(fh.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                        break
                    except BlockingIOError:
                        time.sleep(0.05)
                else:
                    raise ConfigRepoLockError(
                        f"could not acquire repo lock at {self._lock_path} "
                        f"within {self._lock_timeout}s"
                    )
            try:
                yield
            finally:
                fcntl.flock(fh.fileno(), fcntl.LOCK_UN)

    # ── Public API ─────────────────────────────────────────────────────────

    def store_normal(self, device_name: str, text: str, taken_at: datetime) -> tuple[Path, bool, str | None]:
        """Store a normal snapshot in ``<device>/running.cfg``.

        Returns ``(path, committed, commit_sha)``.
        A commit only happens if the content differs from the previous file.
        """
        _validate_name(device_name)
        rel = Path(device_name) / NORMAL_REL
        full = self.root / rel
        full.parent.mkdir(parents=True, exist_ok=True)

        with self._locked():
            previous = full.read_text(encoding="utf-8") if full.exists() else None
            if previous == text:
                head = self._head_sha()
                return full, False, head
            full.write_text(text, encoding="utf-8")
            self._repo.git.add(str(rel))
            summary = _summarise_change(previous, text)
            self._repo.index.commit(
                f"{device_name}: {summary} at {taken_at.isoformat()}"
            )
            return full, True, self._head_sha()

    def store_pre_restore(
        self, device_name: str, text: str, sha256: str, taken_at: datetime
    ) -> tuple[Path, str]:
        """Store a content-addressed pre-restore snapshot. Always committed."""
        _validate_name(device_name)
        rel = (
            Path("pre_restore")
            / device_name
            / f"{taken_at.year:04d}"
            / f"{taken_at.month:02d}"
            / f"{sha256}.cfg"
        )
        full = self.root / rel
        full.parent.mkdir(parents=True, exist_ok=True)

        with self._locked():
            if not full.exists():
                full.write_text(text, encoding="utf-8")
                self._repo.git.add(str(rel))
                self._repo.index.commit(
                    f"pre-restore {device_name} {sha256[:12]} at {taken_at.isoformat()}"
                )
            return full, self._head_sha()

    def read_at(self, commit_sha: str, rel_path: str) -> str:
        """Return the content of ``rel_path`` as of ``commit_sha``."""
        return self._repo.git.show(f"{commit_sha}:{rel_path}")

    def current_content(self, device_name: str) -> str | None:
        """Return the current content of ``<device>/running.cfg`` or None."""
        _validate_name(device_name)
        path = self.root / device_name / NORMAL_REL
        return path.read_text(encoding="utf-8") if path.exists() else None

    def head_sha(self) -> str | None:
        return self._head_sha()

    # ── Internals ──────────────────────────────────────────────────────────

    def _head_sha(self) -> str | None:
        try:
            return self._repo.head.commit.hexsha
        except Exception:
            return None


def _summarise_change(previous: str | None, new: str) -> str:
    """Return a short summary like 'initial' or '3 added, 1 removed'."""
    if previous is None:
        return "initial"
    import difflib
    added = removed = 0
    for line in difflib.unified_diff(
        previous.splitlines(), new.splitlines(), lineterm=""
    ):
        if line.startswith("+") and not line.startswith("+++"):
            added += 1
        elif line.startswith("-") and not line.startswith("---"):
            removed += 1
    if not added and not removed:
        return "no change"
    return f"{added} added, {removed} removed"


def wipe(root: Path) -> None:
    """Delete the configs repo entirely. Used by tests and reset tooling."""
    root = Path(root)
    if root.exists():
        shutil.rmtree(root)
