"""
tidemark.store.repositories
───────────────────────────
Thin repositories over the SQLite tables. No SQL outside this module.
"""

from __future__ import annotations

import re
from datetime import UTC, datetime

from tidemark.core.models import (
    BackupRun,
    Device,
    RunStatus,
    Snapshot,
)
from tidemark.store.db import Database

_NAME_RE = re.compile(r"^[A-Za-z0-9._-]+$")


class InvalidDeviceNameError(ValueError):
    """Raised when a device name fails ``^[A-Za-z0-9._-]+$``."""


def _utc_iso(dt: datetime) -> str:
    if dt.tzinfo is None:
        raise ValueError("naive datetime passed to store; use datetime.now(UTC)")
    return dt.astimezone(UTC).isoformat()


def _from_iso(text: str) -> datetime:
    return datetime.fromisoformat(text)


def _validate_name(name: str) -> None:
    if not name or not _NAME_RE.match(name):
        raise InvalidDeviceNameError(
            f"invalid device name {name!r}; must match ^[A-Za-z0-9._-]+$"
        )


class DeviceRepo:
    """CRUD for the ``devices`` table."""

    def __init__(self, db: Database) -> None:
        self._db = db

    def add(self, device: Device) -> Device:
        _validate_name(device.name)
        now = _utc_iso(datetime.now(UTC))
        cur = self._db.conn.execute(
            """
            INSERT INTO devices
                (name, host, port, profile_id, group_name, enabled,
                 credential_ref, custom_command, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                device.name, device.host, device.port, device.profile_id,
                device.group, int(device.enabled), device.credential_ref,
                device.custom_command, now, now,
            ),
        )
        device.id = int(cur.lastrowid)
        return device

    def update(self, device: Device) -> None:
        if device.id is None:
            raise ValueError("cannot update a device with no id")
        _validate_name(device.name)
        now = _utc_iso(datetime.now(UTC))
        self._db.conn.execute(
            """
            UPDATE devices SET
                name = ?, host = ?, port = ?, profile_id = ?, group_name = ?,
                enabled = ?, credential_ref = ?, custom_command = ?, updated_at = ?
            WHERE id = ?
            """,
            (
                device.name, device.host, device.port, device.profile_id,
                device.group, int(device.enabled), device.credential_ref,
                device.custom_command, now, device.id,
            ),
        )

    def get_by_name(self, name: str) -> Device | None:
        row = self._db.conn.execute(
            "SELECT * FROM devices WHERE name = ?", (name,)
        ).fetchone()
        return _row_to_device(row) if row else None

    def get_by_id(self, device_id: int) -> Device | None:
        row = self._db.conn.execute(
            "SELECT * FROM devices WHERE id = ?", (device_id,)
        ).fetchone()
        return _row_to_device(row) if row else None

    def list(self, enabled_only: bool = False) -> list[Device]:
        sql = "SELECT * FROM devices"
        if enabled_only:
            sql += " WHERE enabled = 1"
        sql += " ORDER BY name"
        return [_row_to_device(r) for r in self._db.conn.execute(sql)]

    def delete(self, device_id: int) -> None:
        self._db.conn.execute("DELETE FROM devices WHERE id = ?", (device_id,))


class SnapshotRepo:
    """CRUD for the ``snapshots`` table."""

    def __init__(self, db: Database) -> None:
        self._db = db

    def add(self, snapshot: Snapshot) -> Snapshot:
        cur = self._db.conn.execute(
            """
            INSERT INTO snapshots
                (device_id, taken_at_utc, sha256, path, size, kind, commit_sha)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                snapshot.device_id,
                _utc_iso(snapshot.taken_at_utc),
                snapshot.sha256,
                snapshot.path,
                snapshot.size,
                snapshot.kind,
                getattr(snapshot, "commit_sha", None),
            ),
        )
        snapshot.id = int(cur.lastrowid)
        return snapshot

    def latest_for_device(self, device_id: int) -> Snapshot | None:
        """Latest snapshot = the snapshot pointed to by the latest run."""
        row = self._db.conn.execute(
            """
            SELECT s.* FROM snapshots s
            JOIN runs r ON r.snapshot_id = s.id
            WHERE s.device_id = ?
            ORDER BY r.id DESC LIMIT 1
            """,
            (device_id,),
        ).fetchone()
        if row is None:
            # No runs yet; fall back to most recent normal snapshot.
            row = self._db.conn.execute(
                """
                SELECT * FROM snapshots
                WHERE device_id = ? AND kind = 'normal'
                ORDER BY id DESC LIMIT 1
                """,
                (device_id,),
            ).fetchone()
        return _row_to_snapshot(row) if row else None

    def get_by_id(self, snapshot_id: int) -> Snapshot | None:
        row = self._db.conn.execute(
            "SELECT * FROM snapshots WHERE id = ?", (snapshot_id,)
        ).fetchone()
        return _row_to_snapshot(row) if row else None

    def get_by_sha(self, device_id: int, sha256: str) -> Snapshot | None:
        row = self._db.conn.execute(
            """
            SELECT * FROM snapshots
            WHERE device_id = ? AND sha256 = ?
            ORDER BY id DESC LIMIT 1
            """,
            (device_id, sha256),
        ).fetchone()
        return _row_to_snapshot(row) if row else None

    def list_for_device(self, device_id: int, limit: int = 50) -> list[Snapshot]:
        rows = self._db.conn.execute(
            """
            SELECT * FROM snapshots WHERE device_id = ?
            ORDER BY id DESC LIMIT ?
            """,
            (device_id, limit),
        )
        return [_row_to_snapshot(r) for r in rows]


class RunRepo:
    """CRUD for the ``runs`` table."""

    def __init__(self, db: Database) -> None:
        self._db = db

    def add(self, run: BackupRun) -> BackupRun:
        cur = self._db.conn.execute(
            """
            INSERT INTO runs
                (device_id, started_at_utc, finished_at_utc, status, error, snapshot_id)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                run.device_id,
                _utc_iso(run.started_at_utc),
                _utc_iso(run.finished_at_utc),
                run.status.value,
                run.error,
                run.snapshot_id,
            ),
        )
        run.id = int(cur.lastrowid)
        return run

    def list_for_device(self, device_id: int, limit: int = 50) -> list[BackupRun]:
        rows = self._db.conn.execute(
            """
            SELECT * FROM runs WHERE device_id = ?
            ORDER BY id DESC LIMIT ?
            """,
            (device_id, limit),
        )
        return [_row_to_run(r) for r in rows]

    def latest_for_device(self, device_id: int) -> BackupRun | None:
        row = self._db.conn.execute(
            "SELECT * FROM runs WHERE device_id = ? ORDER BY id DESC LIMIT 1",
            (device_id,),
        ).fetchone()
        return _row_to_run(row) if row else None


class SettingsRepo:
    """Key/value settings, stored in the ``settings`` table."""

    def __init__(self, db: Database) -> None:
        self._db = db

    def get(self, key: str) -> str | None:
        row = self._db.conn.execute(
            "SELECT value FROM settings WHERE key = ?", (key,)
        ).fetchone()
        return row["value"] if row else None

    def set(self, key: str, value: str) -> None:
        self._db.conn.execute(
            """
            INSERT INTO settings(key, value) VALUES (?, ?)
            ON CONFLICT(key) DO UPDATE SET value = excluded.value
            """,
            (key, value),
        )

    def delete(self, key: str) -> None:
        self._db.conn.execute("DELETE FROM settings WHERE key = ?", (key,))


def _row_to_device(row) -> Device:  # noqa: ANN001 - sqlite3.Row
    return Device(
        id=int(row["id"]),
        name=row["name"],
        host=row["host"],
        port=int(row["port"]),
        profile_id=row["profile_id"],
        group=row["group_name"],
        enabled=bool(row["enabled"]),
        credential_ref=row["credential_ref"],
        custom_command=row["custom_command"],
    )


def _row_to_snapshot(row) -> Snapshot:  # noqa: ANN001
    snap = Snapshot(
        id=int(row["id"]),
        device_id=int(row["device_id"]),
        taken_at_utc=_from_iso(row["taken_at_utc"]),
        sha256=row["sha256"],
        path=row["path"],
        size=int(row["size"]),
        kind=row["kind"],
    )
    setattr(snap, "commit_sha", row["commit_sha"])  # noqa: B010 - extend dataclass
    return snap


def _row_to_run(row) -> BackupRun:  # noqa: ANN001
    return BackupRun(
        id=int(row["id"]),
        device_id=int(row["device_id"]),
        started_at_utc=_from_iso(row["started_at_utc"]),
        finished_at_utc=_from_iso(row["finished_at_utc"]),
        status=RunStatus(row["status"]),
        error=row["error"],
        snapshot_id=int(row["snapshot_id"]) if row["snapshot_id"] is not None else None,
    )
