"""ChatDBCursor — exercises against a tempfile sqlite that mirrors the
relevant slice of macOS chat.db's schema.

We ship a minimal schema with the columns the cursor actually queries.
Real chat.db has many more, but we only care about ROWID + handle + text
+ date + is_from_me + chat_message_join + chat.guid.
"""

from __future__ import annotations

import sqlite3
from datetime import UTC, datetime
from pathlib import Path

from relay.chatdb import APPLE_EPOCH_UNIX, ChatDBCursor


def _build_chatdb(path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(str(path))
    conn.executescript(
        """
        CREATE TABLE handle (
            ROWID INTEGER PRIMARY KEY AUTOINCREMENT,
            id    TEXT
        );
        CREATE TABLE chat (
            ROWID INTEGER PRIMARY KEY AUTOINCREMENT,
            guid  TEXT
        );
        CREATE TABLE message (
            ROWID      INTEGER PRIMARY KEY AUTOINCREMENT,
            handle_id  INTEGER,
            text       TEXT,
            date       INTEGER,
            is_from_me INTEGER
        );
        CREATE TABLE chat_message_join (
            chat_id    INTEGER,
            message_id INTEGER
        );
        """,
    )
    return conn


def _insert_message(
    conn: sqlite3.Connection,
    *,
    handle: str,
    text: str,
    when: datetime,
    is_from_me: int,
    chat_guid: str = "iMessage;-;+39",
) -> int:
    handle_row = conn.execute(
        "INSERT INTO handle (id) VALUES (?)",
        (handle,),
    )
    handle_id = handle_row.lastrowid
    chat_row = conn.execute(
        "INSERT INTO chat (guid) VALUES (?)",
        (chat_guid,),
    )
    chat_id = chat_row.lastrowid
    date_ns = int(
        (when.replace(tzinfo=UTC).timestamp() - APPLE_EPOCH_UNIX) * 1_000_000_000,
    )
    msg_row = conn.execute(
        "INSERT INTO message (handle_id, text, date, is_from_me) VALUES (?, ?, ?, ?)",
        (handle_id, text, date_ns, is_from_me),
    )
    msg_id = msg_row.lastrowid
    conn.execute(
        "INSERT INTO chat_message_join (chat_id, message_id) VALUES (?, ?)",
        (chat_id, msg_id),
    )
    conn.commit()
    assert msg_id is not None
    return int(msg_id)


def test_poll_yields_inbound_messages(tmp_path: Path) -> None:
    db = tmp_path / "chat.db"
    state = tmp_path / "relay.clu.state"
    conn = _build_chatdb(db)
    _insert_message(
        conn,
        handle="+39 333 1111111",
        text="hello",
        when=datetime(2026, 5, 2, 10, 0, 0, tzinfo=UTC),
        is_from_me=0,
    )
    _insert_message(
        conn,
        handle="+39 333 2222222",
        text="world",
        when=datetime(2026, 5, 2, 10, 5, 0, tzinfo=UTC),
        is_from_me=0,
    )
    conn.close()

    cursor = ChatDBCursor(db, state)
    msgs = list(cursor.poll_new())
    assert len(msgs) == 2
    assert msgs[0].body == "hello"
    assert msgs[0].handle == "+39 333 1111111"
    assert msgs[0].chat_guid.startswith("iMessage;")
    assert msgs[0].received_at.startswith("2026-05-02T10:00:00")
    # State file now records the highest rowid.
    assert state.read_text().strip() == str(msgs[1].rowid)


def test_poll_filters_out_outbound_messages(tmp_path: Path) -> None:
    db = tmp_path / "chat.db"
    state = tmp_path / "relay.clu.state"
    conn = _build_chatdb(db)
    _insert_message(
        conn,
        handle="me@x",
        text="my outbound",
        when=datetime(2026, 5, 2, 10, 0, 0, tzinfo=UTC),
        is_from_me=1,
    )
    _insert_message(
        conn,
        handle="them@x",
        text="their inbound",
        when=datetime(2026, 5, 2, 10, 1, 0, tzinfo=UTC),
        is_from_me=0,
    )
    conn.close()

    msgs = list(ChatDBCursor(db, state).poll_new())
    assert len(msgs) == 1
    assert msgs[0].body == "their inbound"


def test_poll_skips_already_seen_via_state_file(tmp_path: Path) -> None:
    db = tmp_path / "chat.db"
    state = tmp_path / "relay.clu.state"
    conn = _build_chatdb(db)
    rowid = _insert_message(
        conn,
        handle="x",
        text="old",
        when=datetime(2026, 5, 2, 10, 0, 0, tzinfo=UTC),
        is_from_me=0,
    )
    conn.close()
    state.write_text(str(rowid), encoding="utf-8")

    msgs = list(ChatDBCursor(db, state).poll_new())
    assert msgs == []


def test_poll_handles_missing_chatdb_gracefully(tmp_path: Path) -> None:
    msgs = list(
        ChatDBCursor(tmp_path / "missing.db", tmp_path / "state.txt").poll_new(),
    )
    assert msgs == []


def test_state_file_atomic_rewrite(tmp_path: Path) -> None:
    """write_last_seen uses a tmp+rename so a crash mid-write doesn't leave
    a half-written state file."""
    state = tmp_path / "relay.clu.state"
    cursor = ChatDBCursor(tmp_path / "chat.db", state)
    cursor.write_last_seen(123)
    assert state.read_text() == "123"
    # A leftover .tmp from a previous failed write should not exist.
    assert not state.with_suffix(state.suffix + ".tmp").exists()
