"""Migrate creates the schema, re-open is idempotent."""

from __future__ import annotations

from pathlib import Path

from tidemark.store.db import Database, migrate

LATEST_SCHEMA_VERSION = 3


def test_migrate_fresh(tmp_path: Path) -> None:
    db = Database(tmp_path / "x.db")
    version = migrate(db)
    assert version == LATEST_SCHEMA_VERSION
    row = db.conn.execute("SELECT version FROM schema_version").fetchone()
    assert int(row["version"]) == LATEST_SCHEMA_VERSION
    for table in ("devices", "runs", "snapshots", "settings", "restore_attempts"):
        assert db.conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name=?",
            (table,),
        ).fetchone() is not None
    db.close()


def test_migrate_idempotent(tmp_path: Path) -> None:
    db = Database(tmp_path / "x.db")
    migrate(db)
    version = migrate(db)
    assert version == LATEST_SCHEMA_VERSION
    count = db.conn.execute("SELECT COUNT(*) AS c FROM schema_version").fetchone()
    assert int(count["c"]) == 1
    db.close()
