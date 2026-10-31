"""Migration v3 adds is_redacted=0 to pre-existing rows."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from tidemark.store.db import _MIGRATIONS, Database, migrate


def test_migration_v3_defaults_existing_rows(tmp_path: Path) -> None:
    """Simulate a v2 DB, insert a row, migrate to v3, confirm default."""

    # Build a v2 DB by applying only migrations 1 and 2.
    db = Database(tmp_path / "t.db")
    conn = db.conn
    conn.execute("CREATE TABLE schema_version (version INTEGER NOT NULL)")
    row = False
    for version, statements in _MIGRATIONS:
        if version > 2:
            break
        conn.execute("BEGIN")
        for sql in statements:
            conn.execute(sql)
        if not row:
            conn.execute("INSERT INTO schema_version(version) VALUES (?)", (version,))
            row = True
        else:
            conn.execute("UPDATE schema_version SET version = ?", (version,))
        conn.execute("COMMIT")

    # Insert a device and a snapshot at v2 (no is_redacted column).
    now = datetime.now(UTC).isoformat()
    conn.execute(
        "INSERT INTO devices (name, host, port, profile_id, credential_ref,"
        " created_at, updated_at) VALUES (?, ?, 22, ?, ?, ?, ?)",
        ("core", "10.0.0.1", "cisco_ios", "default", now, now),
    )
    conn.execute(
        "INSERT INTO snapshots (device_id, taken_at_utc, sha256, path, size, kind)"
        " VALUES (1, ?, ?, '/tmp/x', 10, 'normal')",
        (now, "a" * 64),
    )

    # Migrate to v3.
    version = migrate(db)
    assert version == 3

    # The new column exists and defaults to 0.
    snap = conn.execute(
        "SELECT is_redacted FROM snapshots WHERE id = 1"
    ).fetchone()
    assert int(snap["is_redacted"]) == 0
    db.close()
