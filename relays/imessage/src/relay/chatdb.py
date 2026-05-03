"""Read-only sqlite3 cursor on macOS Messages chat.db.

The chat.db schema is Apple's, not ours — we read three tables and one
join. Don't fight it: we open read-only, query, hand back tuples, close.

Polling model: track the highest seen ROWID from the ``message`` table in
a tiny state file. Each poll cycle queries for ``ROWID > last_seen`` and
yields normalised tuples to the caller. The state file is rewritten
atomically (write+rename) so a crash mid-write doesn't lose the cursor.

Date column conversion: chat.db uses Apple's epoch (2001-01-01 UTC =
``978307200`` Unix seconds) and stores dates as nanoseconds since that
epoch. We convert to UTC ISO 8601 for the bridge.

Full Disk Access (FDA) is required to read chat.db on modern macOS. The
relay process (running as ``clu``) needs FDA granted via System Settings
→ Privacy & Security → Full Disk Access. Operator pre-flight, not a code
concern — see ``SESSION-NOTES.md``.
"""

from __future__ import annotations

import logging
import os
import sqlite3
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Final

logger = logging.getLogger("relay.chatdb")

APPLE_EPOCH_UNIX: Final[int] = 978_307_200  # 2001-01-01 UTC

# Send-direction filter: chat.db's `message.is_from_me` is 1 for outbound
# messages we send, 0 for inbound. The relay only emits inbound events.
_IS_FROM_ME_INBOUND: Final[int] = 0


@dataclass(frozen=True)
class InboundMessage:
    """One inbound message yielded by ``poll_new``."""

    rowid: int
    handle: str
    """The other party's identifier — phone number or email."""

    body: str
    received_at: str
    """ISO 8601 UTC."""

    chat_guid: str


def _apple_ns_to_iso(ns: int | None) -> str:
    """Convert Apple-epoch nanoseconds to ISO 8601 UTC. ``None`` → empty."""
    if not ns:
        return ""
    seconds = APPLE_EPOCH_UNIX + ns / 1_000_000_000
    return datetime.fromtimestamp(seconds, tz=UTC).isoformat()


class ChatDBCursor:
    """Bound to one chat.db file + one state file."""

    def __init__(self, chatdb_path: Path, state_path: Path) -> None:
        self._chatdb = chatdb_path
        self._state = state_path

    # -- state file ----------------------------------------------------

    def read_last_seen(self) -> int:
        """Return the highest ROWID processed in a previous poll, or 0."""
        try:
            return int(self._state.read_text(encoding="utf-8").strip() or "0")
        except FileNotFoundError:
            return 0
        except (OSError, ValueError):
            logger.warning("state_unreadable", extra={"path": str(self._state)})
            return 0

    def write_last_seen(self, rowid: int) -> None:
        """Atomic rewrite via tmp+rename. Creates parent dirs as needed."""
        self._state.parent.mkdir(parents=True, exist_ok=True)
        tmp = self._state.with_suffix(self._state.suffix + ".tmp")
        tmp.write_text(str(int(rowid)), encoding="utf-8")
        os.replace(tmp, self._state)

    # -- bootstrap -----------------------------------------------------

    def state_exists(self) -> bool:
        """Whether the state file is present (i.e. not a fresh run)."""
        return self._state.is_file()

    def bootstrap_to_tail(self) -> int:
        """Skip-to-tail on first run.

        Without this, the first poll sees ``last_seen == 0`` and treats
        the entire chat.db history as fresh inbound — a relay starting
        for the first time on a chat.db with N years of history would
        burst N years of messages through the bridge and fan them out
        to the brain. We don't want that. On a missing state file we
        snapshot the current MAX(ROWID), persist it, and start the
        polling cursor from there. Subsequent restarts honour whatever
        was already persisted.

        Returns the ROWID written, or 0 if chat.db can't be read yet —
        callers should retry; this is the same code path as any other
        chat.db open failure.
        """
        try:
            conn = sqlite3.connect(
                f"file:{self._chatdb}?mode=ro&immutable=1",
                uri=True,
                timeout=2.0,
            )
        except sqlite3.Error as exc:
            logger.warning(
                "chatdb_open_failed",
                extra={"path": str(self._chatdb), "error": str(exc)},
            )
            return 0
        try:
            row = conn.execute(
                "SELECT COALESCE(MAX(ROWID), 0) AS m FROM message",
            ).fetchone()
        finally:
            conn.close()
        max_rowid = int(row[0]) if row is not None else 0
        self.write_last_seen(max_rowid)
        logger.info(
            "chatdb_bootstrapped_to_tail",
            extra={
                "path": str(self._chatdb),
                "starting_rowid": max_rowid,
            },
        )
        return max_rowid

    # -- query ---------------------------------------------------------

    def poll_new(self) -> Iterator[InboundMessage]:
        """Yield messages with ROWID greater than the last-seen cursor.

        Updates the state file *only after* the iterator is exhausted, so
        a caller-side error means we'll re-yield the same messages on the
        next poll. Subscribers are required to be idempotent (they key on
        ``chat_guid + received_at`` for dedupe).
        """
        last = self.read_last_seen()
        try:
            conn = sqlite3.connect(
                f"file:{self._chatdb}?mode=ro&immutable=1",
                uri=True,
                timeout=2.0,
            )
        except sqlite3.Error as exc:
            logger.warning(
                "chatdb_open_failed",
                extra={"path": str(self._chatdb), "error": str(exc)},
            )
            return
        try:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                """
                SELECT m.ROWID         AS rowid,
                       h.id            AS handle,
                       m.text          AS body,
                       m.date          AS date_ns,
                       m.is_from_me    AS is_from_me,
                       c.guid          AS chat_guid
                  FROM message              m
                  JOIN handle               h ON h.ROWID = m.handle_id
                  JOIN chat_message_join    j ON j.message_id = m.ROWID
                  JOIN chat                 c ON c.ROWID = j.chat_id
                 WHERE m.ROWID > ?
                   AND m.is_from_me = ?
                   AND m.text IS NOT NULL
              ORDER BY m.ROWID ASC
                """,
                (last, _IS_FROM_ME_INBOUND),
            ).fetchall()
        finally:
            conn.close()

        if not rows:
            return

        max_rowid = last
        for r in rows:
            rowid = int(r["rowid"])
            yield InboundMessage(
                rowid=rowid,
                handle=str(r["handle"] or ""),
                body=str(r["body"] or ""),
                received_at=_apple_ns_to_iso(r["date_ns"]),
                chat_guid=str(r["chat_guid"] or ""),
            )
            max_rowid = max(max_rowid, rowid)

        if max_rowid > last:
            self.write_last_seen(max_rowid)
