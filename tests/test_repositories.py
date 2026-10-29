"""Round-trip each repository."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest

from tidemark.core.models import BackupRun, Device, RunStatus, Snapshot
from tidemark.store.db import Database, migrate
from tidemark.store.repositories import (
    DeviceRepo,
    RunRepo,
    SettingsRepo,
    SnapshotRepo,
)


@pytest.fixture
def db(tmp_path: Path) -> Database:
    d = Database(tmp_path / "t.db")
    migrate(d)
    yield d  # type: ignore[misc]
    d.close()


def test_device_roundtrip(db: Database) -> None:
    repo = DeviceRepo(db)
    d = Device(name="core", host="10.0.0.1", port=22,
               profile_id="cisco_ios", credential_ref="default")
    d = repo.add(d)
    assert d.id is not None
    got = repo.get_by_name("core")
    assert got is not None and got.host == "10.0.0.1"
    d.host = "10.0.0.2"
    repo.update(d)
    assert repo.get_by_id(d.id).host == "10.0.0.2"
    assert [x.name for x in repo.list()] == ["core"]


def test_snapshot_roundtrip(db: Database) -> None:
    dev = DeviceRepo(db).add(Device(
        name="core", host="10.0.0.1", port=22,
        profile_id="cisco_ios", credential_ref="default",
    ))
    repo = SnapshotRepo(db)
    now = datetime.now(UTC)
    snap = repo.add(Snapshot(device_id=dev.id, taken_at_utc=now,
                             sha256="a" * 64, path="/tmp/x", size=10))
    assert snap.id is not None
    latest = repo.latest_for_device(dev.id)
    assert latest is not None and latest.sha256 == "a" * 64
    assert [s.id for s in repo.list_for_device(dev.id)] == [snap.id]


def test_run_roundtrip(db: Database) -> None:
    dev = DeviceRepo(db).add(Device(
        name="core", host="10.0.0.1", port=22,
        profile_id="cisco_ios", credential_ref="default",
    ))
    now = datetime.now(UTC)
    repo = RunRepo(db)
    run = repo.add(BackupRun(
        device_id=dev.id, started_at_utc=now, finished_at_utc=now,
        status=RunStatus.SUCCESS,
    ))
    assert run.id is not None
    assert repo.list_for_device(dev.id)[0].status is RunStatus.SUCCESS


def test_settings_roundtrip(db: Database) -> None:
    repo = SettingsRepo(db)
    assert repo.get("k") is None
    repo.set("k", "v")
    assert repo.get("k") == "v"
    repo.set("k", "v2")
    assert repo.get("k") == "v2"
    repo.delete("k")
    assert repo.get("k") is None
