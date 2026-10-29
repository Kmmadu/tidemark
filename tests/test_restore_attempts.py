"""Restore attempts audit table: pending, success, failed, unverified, sweep."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

from tidemark.core.models import Device
from tidemark.store.db import Database, migrate
from tidemark.store.repositories import DeviceRepo
from tidemark.store.restore_attempts import AttemptOutcome, RestoreAttemptsRepo


def _setup(tmp_path: Path):
    db = Database(tmp_path / "t.db")
    migrate(db)
    device = DeviceRepo(db).add(Device(
        name="core", host="10.0.0.1", port=22,
        profile_id="cisco_ios", credential_ref="default",
    ))
    return db, device


def test_pending_then_success(tmp_path: Path) -> None:
    db, dev = _setup(tmp_path)
    repo = RestoreAttemptsRepo(db)
    a = repo.begin(dev.id, None, "kmtech", "hash")
    assert a.outcome is AttemptOutcome.PENDING
    repo.finish(a.id, AttemptOutcome.SUCCESS)
    assert repo.last_unverified_for_device(dev.id) is None


def test_stale_pending_swept(tmp_path: Path) -> None:
    db, dev = _setup(tmp_path)
    repo = RestoreAttemptsRepo(db)
    a = repo.begin(dev.id, None, "kmtech", "hash")
    db.conn.execute(
        "UPDATE restore_attempts SET started_at_utc = ? WHERE id = ?",
        ((datetime.now(UTC) - timedelta(minutes=15)).isoformat(), a.id),
    )
    swept = repo.sweep_stale()
    assert swept == 1
    unv = repo.last_unverified_for_device(dev.id)
    assert unv is not None and unv.outcome is AttemptOutcome.UNVERIFIED
