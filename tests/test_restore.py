"""plan_restore: mode gating, hash stability, target integrity."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import patch

import pytest

from tidemark.core import engine as engine_mod
from tidemark.core.credentials import Credentials
from tidemark.core.driver import FetchResult
from tidemark.core.models import Device, RestoreMode, Snapshot
from tidemark.core.profiles import ProfileRegistry
from tidemark.core.restore import (
    RestoreConfirmationError,
    RestoreModeError,
    plan_restore,
)
from tidemark.store.db import Database, migrate
from tidemark.store.git_repo import ConfigRepo
from tidemark.store.repositories import DeviceRepo, SnapshotRepo
from tidemark.store.service import backup_and_persist

CONFIG1 = """\
hostname r1
!
interface Gi0/1
 ip address 10.0.0.1 255.255.255.0
!
"""
CONFIG2 = CONFIG1.replace("10.0.0.1", "10.0.0.2")


def _setup(tmp_path: Path):
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

    return db, repo, device, profile, run


def test_plan_mode_none_rejected(tmp_path: Path) -> None:
    db, repo, device, profile, run = _setup(tmp_path)
    run(CONFIG1)
    profile_with_none = profile.__class__(
        id="custom", display_name="Custom", netmiko_device_type="generic",
        fetch_commands=["show run"], restore=RestoreMode.NONE,
    )
    snaps = SnapshotRepo(db).list_for_device(device.id)
    target_id = snaps[0].id
    with pytest.raises(RestoreModeError):
        plan_restore(device, profile_with_none, target_id, db, repo)


def test_plan_target_pre_restore_rejected(tmp_path: Path) -> None:
    db, repo, device, profile, run = _setup(tmp_path)
    run(CONFIG1)
    now = datetime.now(UTC)
    pre_sha = "a" * 64
    repo.store_pre_restore("core", CONFIG1, pre_sha, now)
    pre = SnapshotRepo(db).add(Snapshot(
        device_id=device.id, taken_at_utc=now, sha256=pre_sha,
        path=str(repo.root / "pre_restore" / "core"),
        size=len(CONFIG1), kind="pre_restore",
    ))
    with pytest.raises(RestoreConfirmationError):
        plan_restore(device, profile, pre.id or 0, db, repo)


def test_plan_hash_stable(tmp_path: Path) -> None:
    db, repo, device, profile, run = _setup(tmp_path)
    run(CONFIG1)
    run(CONFIG2)
    snaps = SnapshotRepo(db).list_for_device(device.id)
    target = snaps[-1]  # oldest snapshot = CONFIG1
    plan_a = plan_restore(device, profile, target.id or 0, db, repo)
    plan_b = plan_restore(device, profile, target.id or 0, db, repo)
    assert plan_a.plan_hash == plan_b.plan_hash
    assert plan_a.confirm_token == f"core@{target.id}"


def test_plan_confirms_token_removals_suffix(tmp_path: Path) -> None:
    db, repo, device, profile, run = _setup(tmp_path)
    run(CONFIG1)
    run(CONFIG2)
    snaps = SnapshotRepo(db).list_for_device(device.id)
    target = snaps[-1]
    plan = plan_restore(device, profile, target.id or 0, db, repo,
                        allow_removals=True)
    assert plan.confirm_token.endswith("+rm")


def test_plan_expected_post_overwrites_ip(tmp_path: Path) -> None:
    db, repo, device, profile, run = _setup(tmp_path)
    run(CONFIG1)
    run(CONFIG2)
    snaps = SnapshotRepo(db).list_for_device(device.id)
    target = snaps[-1]  # CONFIG1
    plan = plan_restore(device, profile, target.id or 0, db, repo)
    assert plan.status == "ready"
    assert "ip address 10.0.0.1 255.255.255.0" in plan.expected_post_text
    assert "ip address 10.0.0.2 255.255.255.0" not in plan.expected_post_text
