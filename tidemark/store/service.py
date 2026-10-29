"""
tidemark.store.service
──────────────────────
Glue between the engine and the store.

Rules (M2a):
- A new snapshot row is created **whenever the current hash differs from the
  device's latest snapshot hash**. A→B→A produces three rows and three
  commits.
- ``UNCHANGED`` runs point at the *latest* snapshot (same id as the previous
  run's snapshot id).
- Normal snapshots go to ``<device>/running.cfg``; pre-restore snapshots
  (M2b) go to ``pre_restore/<device>/<YYYY>/<MM>/<sha>.cfg``.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime

from tidemark.core.credentials import Credentials
from tidemark.core.engine import run_backup
from tidemark.core.models import (
    BackupResult,
    BackupRun,
    Device,
    RunStatus,
    Snapshot,
    VendorProfile,
)
from tidemark.store.db import Database
from tidemark.store.git_repo import ConfigRepo
from tidemark.store.repositories import RunRepo, SnapshotRepo

logger = logging.getLogger(__name__)


def backup_and_persist(
    device: Device,
    profile: VendorProfile,
    credentials: Credentials,
    db: Database,
    config_repo: ConfigRepo,
    *,
    previous_text: str | None = None,
    retries: int = 2,
) -> BackupResult:
    """Run a backup, persist the snapshot, record the run."""
    if device.id is None:
        raise ValueError("device.id is required; add the device to the repo first")

    snapshot_repo = SnapshotRepo(db)
    run_repo = RunRepo(db)

    if previous_text is None:
        latest = snapshot_repo.latest_for_device(device.id)
        if latest is not None and latest.path:
            try:
                previous_text = config_repo.current_content(device.name)
            except Exception as exc:  # noqa: BLE001
                logger.warning("cannot read previous snapshot: %s", exc)

    result = run_backup(
        device, profile, credentials,
        previous_text=previous_text,
        retries=retries,
    )

    snapshot_id: int | None = None
    if result.status in (RunStatus.SUCCESS, RunStatus.UNCHANGED) and result.sha256:
        latest = snapshot_repo.latest_for_device(device.id)
        taken = result.finished_at_utc or datetime.now(UTC)

        if latest is not None and latest.sha256 == result.sha256:
            # Same content as latest snapshot: reuse the row, no commit.
            snapshot_id = latest.id
        else:
            path, committed, commit_sha = config_repo.store_normal(
                device.name, result.normalised_text or "", taken,
            )
            snap = Snapshot(
                device_id=device.id,
                taken_at_utc=taken,
                sha256=result.sha256,
                path=str(path),
                size=len(result.normalised_text or ""),
                kind="normal",
            )
            setattr(snap, "commit_sha", commit_sha)  # noqa: B010
            snapshot_repo.add(snap)
            snapshot_id = snap.id
            logger.info(
                "snapshot for %s: sha=%s committed=%s",
                device.name, result.sha256[:12], committed,
            )

    run = BackupRun(
        device_id=device.id,
        started_at_utc=result.started_at_utc,
        finished_at_utc=result.finished_at_utc,
        status=result.status,
        error=result.error,
        snapshot_id=snapshot_id,
    )
    run_repo.add(run)
    return result
