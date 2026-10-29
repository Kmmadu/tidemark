"""End-to-end through the store: fake driver, real SQLite, real git repo."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest

from tidemark.core import engine as engine_mod
from tidemark.core.credentials import Credentials
from tidemark.core.driver import FetchResult
from tidemark.core.models import Device, RunStatus
from tidemark.core.profiles import ProfileRegistry
from tidemark.store.db import Database, migrate
from tidemark.store.git_repo import ConfigRepo
from tidemark.store.repositories import DeviceRepo, RunRepo, SnapshotRepo
from tidemark.store.service import backup_and_persist


def _count_commits(repo_path: Path) -> int:
    import subprocess
    return int(subprocess.run(
        ["git", "-C", str(repo_path), "rev-list", "--count", "HEAD"],
        check=True, capture_output=True, text=True,
    ).stdout.strip())


@pytest.fixture
def setup(tmp_path: Path) -> tuple[Database, ConfigRepo, Device]:
    db = Database(tmp_path / "t.db")
    migrate(db)
    repo = ConfigRepo(tmp_path / "configs")
    device = DeviceRepo(db).add(Device(
        name="core", host="10.0.0.1", port=22,
        profile_id="cisco_ios", credential_ref="default",
    ))
    return db, repo, device


def test_backup_persists_snapshot_run_and_commit(setup) -> None:
    db, repo, device = setup
    profile = ProfileRegistry().get("cisco_ios")

    with patch.object(engine_mod.Driver, "fetch",
                      return_value=FetchResult(text="hostname r1\n")):
        backup_and_persist(device, profile, Credentials("u", "p"), db, repo, retries=0)

    snap = SnapshotRepo(db).latest_for_device(device.id)
    assert snap is not None
    runs = RunRepo(db).list_for_device(device.id)
    assert runs[0].status is RunStatus.SUCCESS
    assert _count_commits(repo.root) >= 1


def test_second_identical_run_no_new_commit(setup) -> None:
    db, repo, device = setup
    profile = ProfileRegistry().get("cisco_ios")

    with patch.object(engine_mod.Driver, "fetch",
                      return_value=FetchResult(text="hostname r1\n")):
        backup_and_persist(device, profile, Credentials("u", "p"), db, repo, retries=0)
        before = _count_commits(repo.root)
        backup_and_persist(device, profile, Credentials("u", "p"), db, repo, retries=0)
    assert _count_commits(repo.root) == before


def test_changed_line_creates_one_new_commit(setup) -> None:
    db, repo, device = setup
    profile = ProfileRegistry().get("cisco_ios")

    with patch.object(engine_mod.Driver, "fetch",
                      return_value=FetchResult(text="hostname r1\n")):
        backup_and_persist(device, profile, Credentials("u", "p"), db, repo, retries=0)
        before = _count_commits(repo.root)

    with patch.object(engine_mod.Driver, "fetch",
                      return_value=FetchResult(text="hostname r1\ninterface Gi0/1\n")):
        backup_and_persist(device, profile, Credentials("u", "p"), db, repo, retries=0)
        after = _count_commits(repo.root)

    assert after == before + 1
