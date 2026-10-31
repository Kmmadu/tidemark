"""plan_restore refuses redacted targets and redacted-current states."""

from __future__ import annotations

import hashlib
from pathlib import Path
from unittest.mock import patch

import pytest

from tidemark.core import engine as engine_mod
from tidemark.core.credentials import Credentials
from tidemark.core.driver import FetchResult
from tidemark.core.models import Device
from tidemark.core.profiles import ProfileRegistry
from tidemark.core.redact import REDACTED_MARKER
from tidemark.core.restore import RestoreModeError, plan_restore
from tidemark.store.db import Database, migrate
from tidemark.store.git_repo import ConfigRepo
from tidemark.store.repositories import DeviceRepo, SettingsRepo, SnapshotRepo
from tidemark.store.service import backup_and_persist

CONFIG = "hostname r1\ninterface Gi0/1\n ip address 10.0.0.1 255.255.255.0\n"


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


def test_refuse_redacted_flag(tmp_path: Path) -> None:
    db, repo, device, profile, run = _setup(tmp_path)
    run(CONFIG)
    snap = SnapshotRepo(db).list_for_device(device.id)[0]
    snap.is_redacted = True
    db.conn.execute("UPDATE snapshots SET is_redacted = 1 WHERE id = ?", (snap.id,))
    with pytest.raises(RestoreModeError, match="stored with redaction"):
        plan_restore(device, profile, snap.id, db, repo)


def test_refuse_content_marker(tmp_path: Path) -> None:
    db, repo, device, profile, run = _setup(tmp_path)
    run(CONFIG)
    snap = SnapshotRepo(db).list_for_device(device.id)[0]
    # Rewrite the git content to contain the marker; is_redacted stays 0.
    content = repo.current_content(device.name) or ""
    new_content = content.replace("hostname r1", f"hostname {REDACTED_MARKER}")
    repo.store_normal(device.name, new_content, snap.taken_at_utc)

    new_sha = hashlib.sha256(new_content.rstrip("\n").encode()).hexdigest()
    snap2 = SnapshotRepo(db).add(type(snap)(
        device_id=device.id,
        taken_at_utc=snap.taken_at_utc,
        sha256=new_sha,
        path=snap.path,
        size=len(new_content),
        kind="normal",
    ))
    snap2.commit_sha = repo.head_sha()

    with pytest.raises(RestoreModeError, match="contains"):
        plan_restore(device, profile, snap2.id, db, repo)


def test_refuse_when_store_raw_false(tmp_path: Path) -> None:
    db, repo, device, profile, run = _setup(tmp_path)
    run(CONFIG)
    SettingsRepo(db).set("store_raw", "false")
    snap = SnapshotRepo(db).list_for_device(device.id)[0]
    with pytest.raises(RestoreModeError, match="store_raw=false"):
        plan_restore(device, profile, snap.id, db, repo)
