"""SQLite-backed dedup store.

The brain's only long-lived state. One table:

- ``processed_events`` — keyed by the bridge's ``event_id``. Skip an
  envelope at the top of every handler if it's here. Important because
  ``brains_shared.eventbus`` reconnects on close and the bridge's
  pub/sub is fire-and-forget; the brain may see the same envelope twice
  across a reconnect window.

Drafts used to live here too. They moved to the bridge (the bridge
owns the approval lifecycle now). The brain just calls
``brains_shared.agent.create_draft`` after an LLM pass; the operator
manages the draft via ``scripts/brain-drafts.py`` against the bridge's
HTTP API. The brain is purely a draft *producer* now.

Connection model: one ``sqlite3.Connection`` per brain process. SQLite
is fast enough that the threading bridge isn't worth it here. All
public functions are async wrappers via ``asyncio.to_thread`` so the
brain's event loop never blocks on disk.
"""

from __future__ import annotations

import asyncio
import sqlite3
from datetime import UTC, datetime
from pathlib import Path

_SCHEMA: tuple[str, ...] = (
    """
    CREATE TABLE IF NOT EXISTS processed_events (
        event_id     TEXT PRIMARY KEY,
        topic        TEXT NOT NULL,
        processed_at TEXT NOT NULL
    );
    """,
)


def _now_iso() -> str:
    return datetime.now(UTC).isoformat()


def _connect(path: Path) -> sqlite3.Connection:
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path), timeout=2.0, isolation_level=None)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL;")
    for stmt in _SCHEMA:
        conn.executescript(stmt)
    return conn


class State:
    """Async wrapper around a SQLite connection."""

    def __init__(self, path: Path) -> None:
        self._path = path
        self._conn: sqlite3.Connection | None = None

    async def open(self) -> None:
        self._conn = await asyncio.to_thread(_connect, self._path)

    async def close(self) -> None:
        if self._conn is not None:
            await asyncio.to_thread(self._conn.close)
            self._conn = None

    @property
    def conn(self) -> sqlite3.Connection:
        if self._conn is None:
            raise RuntimeError("State.open() must be called before use.")
        return self._conn

    # -- dedup ---------------------------------------------------------

    async def is_processed(self, event_id: str) -> bool:
        return await asyncio.to_thread(self._sync_is_processed, event_id)

    def _sync_is_processed(self, event_id: str) -> bool:
        cur = self.conn.execute(
            "SELECT 1 FROM processed_events WHERE event_id = ? LIMIT 1",
            (event_id,),
        )
        return cur.fetchone() is not None

    async def mark_processed(self, event_id: str, topic: str) -> None:
        await asyncio.to_thread(self._sync_mark_processed, event_id, topic)

    def _sync_mark_processed(self, event_id: str, topic: str) -> None:
        # `INSERT OR IGNORE` makes double-mark a no-op (concurrent reconnect
        # could race the same event); the dedup contract only cares that
        # `is_processed` returns True afterwards.
        self.conn.execute(
            "INSERT OR IGNORE INTO processed_events (event_id, topic, processed_at) "
            "VALUES (?, ?, ?)",
            (event_id, topic, _now_iso()),
        )


__all__ = ["State"]
