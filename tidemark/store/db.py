"""
tidemark.store.db
─────────────────
SQLite database for inventory, runs, snapshots, attempts and settings.

- WAL journal mode.
- ``schema_version`` table plus a forward-only list of migrations.
- **One connection per thread**, via ``threading.local``. SQLite connections
  are not safe to share across threads; ``check_same_thread=False`` is a lie.
- ``foreign_keys=ON`` and ``busy_timeout=5000`` on every connection.

No SQL lives outside ``tidemark/store/``.
"""

from __future__ import annotations

import logging
import sqlite3
import threading
from pathlib import Path

logger = logging.getLogger(__name__)


_MIGRATIONS: list[tuple[int, list[str]]] = [
    (
        1,
        [
            """
            CREATE TABLE devices (
                id             INTEGER PRIMARY KEY AUTOINCREMENT,
                name           TEXT NOT NULL UNIQUE,
                host           TEXT NOT NULL,
                port           INTEGER NOT NULL DEFAULT 22,
                profile_id     TEXT NOT NULL,
                group_name     TEXT,
                enabled        INTEGER NOT NULL DEFAULT 1,
                credential_ref TEXT NOT NULL,
                custom_command TEXT,
                created_at     TEXT NOT NULL,
                updated_at     TEXT NOT NULL
            )
            """,
            """
            CREATE TABLE runs (
                id               INTEGER PRIMARY KEY AUTOINCREMENT,
                device_id        INTEGER NOT NULL REFERENCES devices(id) ON DELETE CASCADE,
                started_at_utc   TEXT NOT NULL,
                finished_at_utc  TEXT NOT NULL,
                status           TEXT NOT NULL,
                error            TEXT,
                snapshot_id      INTEGER REFERENCES snapshots(id)
            )
            """,
            """
            CREATE TABLE snapshots (
                id            INTEGER PRIMARY KEY AUTOINCREMENT,
                device_id     INTEGER NOT NULL REFERENCES devices(id) ON DELETE CASCADE,
                taken_at_utc  TEXT NOT NULL,
                sha256        TEXT NOT NULL,
                path          TEXT NOT NULL,
                size          INTEGER NOT NULL,
                kind          TEXT NOT NULL DEFAULT 'normal'
            )
            """,
            "CREATE INDEX idx_runs_device ON runs(device_id, started_at_utc)",
            "CREATE INDEX idx_snapshots_device ON snapshots(device_id, taken_at_utc)",
            "CREATE INDEX idx_snapshots_sha ON snapshots(device_id, sha256)",
            """
            CREATE TABLE settings (
                key   TEXT PRIMARY KEY,
                value TEXT NOT NULL
            )
            """,
        ],
    ),
    (
        2,
        [
            # M2a: commit_sha on snapshots, restore_attempts audit table,
            # credential-store backend setting is a plain key in settings.
            "ALTER TABLE snapshots ADD COLUMN commit_sha TEXT",
            """
            CREATE TABLE restore_attempts (
                id               INTEGER PRIMARY KEY AUTOINCREMENT,
                device_id        INTEGER NOT NULL REFERENCES devices(id) ON DELETE CASCADE,
                snapshot_id      INTEGER REFERENCES snapshots(id) ON DELETE SET NULL,
                started_at_utc   TEXT NOT NULL,
                finished_at_utc  TEXT,
                outcome          TEXT NOT NULL,
                operator         TEXT NOT NULL,
                plan_hash        TEXT NOT NULL,
                notes            TEXT
            )
            """,
            "CREATE INDEX idx_attempts_device ON restore_attempts(device_id, started_at_utc)",
            "CREATE INDEX idx_attempts_outcome ON restore_attempts(outcome, started_at_utc)",
        ],
    ),
]


class Database:
    """A per-thread SQLite connection pool of exactly one connection."""

    def __init__(self, path: Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._local = threading.local()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.path, isolation_level=None, timeout=5.0)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA foreign_keys=ON")
        conn.execute("PRAGMA busy_timeout=5000")
        return conn

    @property
    def conn(self) -> sqlite3.Connection:
        conn = getattr(self._local, "conn", None)
        if conn is None:
            conn = self._connect()
            self._local.conn = conn
        return conn

    def close(self) -> None:
        """Close the connection **for the calling thread only**."""
        conn = getattr(self._local, "conn", None)
        if conn is not None:
            conn.close()
            self._local.conn = None

    def close_all(self) -> None:
        """Best-effort: close the calling thread's connection. Other threads'
        connections are closed by their thread when it exits. Do not rely on
        this as a global shutdown; use process exit for that."""
        self.close()

    def __enter__(self) -> Database:
        return self

    def __exit__(self, *_: object) -> None:
        self.close()


def migrate(db: Database) -> int:
    """Apply pending migrations. Returns the resulting schema version."""
    conn = db.conn
    conn.execute(
        "CREATE TABLE IF NOT EXISTS schema_version (version INTEGER NOT NULL)"
    )
    row = conn.execute("SELECT version FROM schema_version").fetchone()
    current = int(row["version"]) if row is not None else 0

    for version, statements in _MIGRATIONS:
        if version <= current:
            continue
        logger.info("applying migration %d", version)
        conn.execute("BEGIN")
        try:
            for sql in statements:
                conn.execute(sql)
            if row is None:
                conn.execute(
                    "INSERT INTO schema_version(version) VALUES (?)", (version,)
                )
                row = True  # type: ignore[assignment]
            else:
                conn.execute("UPDATE schema_version SET version = ?", (version,))
            conn.execute("COMMIT")
        except Exception:
            conn.execute("ROLLBACK")
            raise
        current = version

    return current
