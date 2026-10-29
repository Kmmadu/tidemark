"""A→B→A creates three snapshot rows and three commits."""

from __future__ import annotations

import subprocess
from pathlib import Path
from unittest.mock import patch

from tidemark.core import engine as engine_mod
from tidemark.core.credentials import Credentials
from tidemark.core.driver import FetchResult
from tidemark.core.models import Device
from tidemark.core.profiles import ProfileRegistry
from tidemark.store.db import Database, migrate
from tidemark.store.git_repo import ConfigRepo
from tidemark.store.repositories import DeviceRepo, SnapshotRepo
from tidemark.store.service import backup_and_persist


def _commits(repo_root: Path) -> int:
    return int(subprocess.run(
        ["git", "-C", str(repo_root), "rev-list", "--count", "HEAD"],
        check=True, capture_output=True, text=True,
    ).stdout.strip())


def test_revert_creates_new_snapshot_and_commit(tmp_path: Path) -> None:
    db = Database(tmp_path / "t.db")
    migrate(db)
    repo = ConfigRepo(tmp_path / "configs")
    device = DeviceRepo(db).add(Device(
        name="core", host="10.0.0.1", port=22,
        profile_id="cisco_ios", credential_ref="default",
    ))
    profile = ProfileRegistry().get("cisco_ios")

    def run(text: str) -> None:
        with patch.object(engine_mod.Driver, "fetch",
                          return_value=FetchResult(text=text)):
            backup_and_persist(device, profile, Credentials("u", "p"),
                               db, repo, retries=0)

    run("hostname r1\n")
    run("hostname r1\ninterface Gi0/1\n")
    run("hostname r1\n")

    snaps = SnapshotRepo(db).list_for_device(device.id)
    assert len(snaps) == 3
    assert _commits(repo.root) == 3
    assert snaps[0].sha256 == snaps[2].sha256  # A' has same sha as A
