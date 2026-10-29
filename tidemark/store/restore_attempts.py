"""
tidemark.store.restore_attempts
───────────────────────────────
Audit log of restore attempts. Written before any SSH work, so a crash
between "user typed the token" and "connected to the device" leaves a
``pending`` row that the next session can flag as ``unverified``.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from enum import StrEnum

from tidemark.store.db import Database


class AttemptOutcome(StrEnum):
    PENDING = "pending"
    SUCCESS = "success"
    FAILED = "failed"
    UNVERIFIED = "unverified"


STALE_PENDING_AFTER = timedelta(minutes=10)


@dataclass
class RestoreAttempt:
    id: int | None
    device_id: int
    snapshot_id: int | None
    started_at_utc: datetime
    finished_at_utc: datetime | None
    outcome: AttemptOutcome
    operator: str
    plan_hash: str
    notes: str | None


class RestoreAttemptsRepo:
    def __init__(self, db: Database) -> None:
        self._db = db

    def begin(
        self,
        device_id: int,
        snapshot_id: int | None,
        operator: str,
        plan_hash: str,
    ) -> RestoreAttempt:
        now = datetime.now(UTC)
        cur = self._db.conn.execute(
            """
            INSERT INTO restore_attempts
                (device_id, snapshot_id, started_at_utc, finished_at_utc,
                 outcome, operator, plan_hash, notes)
            VALUES (?, ?, ?, NULL, ?, ?, ?, NULL)
            """,
            (
                device_id, snapshot_id, now.isoformat(),
                AttemptOutcome.PENDING.value, operator, plan_hash,
            ),
        )
        return RestoreAttempt(
            id=int(cur.lastrowid),
            device_id=device_id,
            snapshot_id=snapshot_id,
            started_at_utc=now,
            finished_at_utc=None,
            outcome=AttemptOutcome.PENDING,
            operator=operator,
            plan_hash=plan_hash,
            notes=None,
        )

    def finish(
        self,
        attempt_id: int,
        outcome: AttemptOutcome,
        notes: str | None = None,
    ) -> None:
        self._db.conn.execute(
            """
            UPDATE restore_attempts
            SET finished_at_utc = ?, outcome = ?, notes = ?
            WHERE id = ?
            """,
            (datetime.now(UTC).isoformat(), outcome.value, notes, attempt_id),
        )

    def sweep_stale(self) -> int:
        """Mark pending attempts older than 10 minutes as unverified.

        Returns the number of rows updated. Called on CLI startup so that
        an ``unverified`` restore from a previous crashed session is
        visible.
        """
        cutoff = (datetime.now(UTC) - STALE_PENDING_AFTER).isoformat()
        cur = self._db.conn.execute(
            """
            UPDATE restore_attempts
            SET outcome = ?, finished_at_utc = ?, notes = 'stale pending swept'
            WHERE outcome = ? AND started_at_utc < ?
            """,
            (
                AttemptOutcome.UNVERIFIED.value,
                datetime.now(UTC).isoformat(),
                AttemptOutcome.PENDING.value,
                cutoff,
            ),
        )
        return cur.rowcount or 0

    def last_unverified_for_device(self, device_id: int) -> RestoreAttempt | None:
        row = self._db.conn.execute(
            """
            SELECT * FROM restore_attempts
            WHERE device_id = ? AND outcome = ?
            ORDER BY id DESC LIMIT 1
            """,
            (device_id, AttemptOutcome.UNVERIFIED.value),
        ).fetchone()
        return _row_to_attempt(row) if row else None


def _row_to_attempt(row) -> RestoreAttempt:  # noqa: ANN001
    return RestoreAttempt(
        id=int(row["id"]),
        device_id=int(row["device_id"]),
        snapshot_id=int(row["snapshot_id"]) if row["snapshot_id"] is not None else None,
        started_at_utc=datetime.fromisoformat(row["started_at_utc"]),
        finished_at_utc=(
            datetime.fromisoformat(row["finished_at_utc"])
            if row["finished_at_utc"] else None
        ),
        outcome=AttemptOutcome(row["outcome"]),
        operator=row["operator"],
        plan_hash=row["plan_hash"],
        notes=row["notes"],
    )
