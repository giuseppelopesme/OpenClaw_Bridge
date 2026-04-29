"""SQL migration files + tiny runner for bridge-owned SQLite databases.

Each `.sql` file in this package is applied once per database, in
lexicographic order. Files are grouped by prefix so each database sees only
its own migrations:

    apply_migrations(conn, "idempotency")  # applies idempotency_*.sql
    apply_migrations(conn, "telemetry")    # applies telemetry_*.sql

Re-runs are no-ops; an internal `_migrations` table tracks applied filenames.
Migrations are intentionally minimal — no down-migrations, no transactional
rollback across files. Each file's contents run inside a single transaction;
either it applies cleanly or it doesn't.
"""

from __future__ import annotations

import sqlite3
from importlib.resources import files
from pathlib import Path

_PACKAGE = "bridge.migrations"


def _migration_files(prefix: str) -> list[tuple[str, str]]:
    """Return [(name, sql)] for every .sql file under the package matching prefix."""
    root = files(_PACKAGE)
    out: list[tuple[str, str]] = []
    for resource in root.iterdir():
        name = resource.name
        if not name.endswith(".sql") or not name.startswith(prefix):
            continue
        sql = resource.read_text(encoding="utf-8")
        out.append((name, sql))
    out.sort(key=lambda nv: nv[0])
    return out


def apply_migrations(conn: sqlite3.Connection, prefix: str) -> list[str]:
    """Apply any unapplied .sql files matching `prefix`. Returns names just applied."""
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS _migrations (
            name        TEXT PRIMARY KEY,
            applied_at  INTEGER NOT NULL
        )
        """,
    )
    applied = {row[0] for row in conn.execute("SELECT name FROM _migrations")}
    new_runs: list[str] = []
    for name, sql in _migration_files(prefix):
        if name in applied:
            continue
        with conn:
            conn.executescript(sql)
            conn.execute(
                "INSERT INTO _migrations (name, applied_at) VALUES (?, strftime('%s','now'))",
                (name,),
            )
        new_runs.append(name)
    return new_runs


def open_with_migrations(db_path: Path, prefix: str) -> sqlite3.Connection:
    """Open `db_path` (creating parents), apply migrations, return the connection."""
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path, isolation_level=None, check_same_thread=False)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    apply_migrations(conn, prefix)
    return conn
