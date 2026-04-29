"""Idempotency-Key middleware (POST endpoints).

Per `docs/api-contract.md`:

- POSTs may carry an `Idempotency-Key` header. The bridge stores
  `(key, body_hash) -> response` for 24h.
- Same key, same body hash → returns the cached response with
  `X-Idempotency-Replay: true`.
- Same key, different body hash → `409 idempotency_replay`.
- No key supplied → request executes normally (v1 policy; v1.1 will require).

Implementation notes:

- Plain ASGI middleware (no `BaseHTTPMiddleware`) for the same reasons spelled
  out in `bridge.middleware`: anyio exception-handling in the framework
  middleware short-circuits post-response code on exceptions.
- Storage is SQLite at `~/.openclaw/idempotency.db` (separate file from
  `telemetry.db`). Schema is in `bridge/src/bridge/migrations/`.
- We buffer the request body into memory before computing the hash, then
  replay it via a custom `receive` callable. Vault-write payloads are small;
  if a future endpoint takes large bodies we can stream-hash instead.
- Cached responses are stored as raw bytes plus headers, replayed via direct
  `send` so middleware ordering does not double-stamp `X-Request-ID` etc.
- Pruning is lazy: every lookup deletes rows older than `TTL_SECONDS`. No
  background task.
"""

from __future__ import annotations

import hashlib
import json
import logging
import sqlite3
import time
from typing import Final

from starlette.types import ASGIApp, Message, Receive, Scope, Send

logger = logging.getLogger("bridge.idempotency")

TTL_SECONDS: Final[int] = 24 * 60 * 60
_IDEMPOTENCY_HEADER: Final[bytes] = b"idempotency-key"
_REPLAY_HEADER: Final[bytes] = b"x-idempotency-replay"

# Hop-by-hop and per-response framing headers we strip from cached responses.
# `content-length` is recomputed at replay; `x-request-id` is freshly stamped
# by `RequestIDMiddleware` per request.
_STRIPPED_RESPONSE_HEADERS: Final[frozenset[bytes]] = frozenset(
    {b"content-length", b"x-request-id", b"x-bridge-version"},
)


def _read_header(scope: Scope, name: bytes) -> str | None:
    headers: list[tuple[bytes, bytes]] = scope.get("headers", [])
    for header_name, header_value in headers:
        if header_name == name:
            return header_value.decode("latin-1")
    return None


class IdempotencyMiddleware:
    """Cache POST responses keyed on (Idempotency-Key, sha256(body))."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or scope.get("method") != "POST":
            await self.app(scope, receive, send)
            return

        key = _read_header(scope, _IDEMPOTENCY_HEADER)
        if not key:
            await self.app(scope, receive, send)
            return

        # Buffer the request body so we can hash it then replay it.
        body, more_messages = await _drain_body(receive)
        body_hash = hashlib.sha256(body).hexdigest()

        rid = _request_id(scope)
        conn = _conn(scope)
        if conn is None:  # No store wired up — behave as no-op.
            await self.app(scope, _replayer(body, more_messages), send)
            return

        _prune_expired(conn)
        cached = _lookup(conn, key)
        if cached is not None:
            cached_hash, cached_status, cached_headers, cached_body = cached
            if cached_hash != body_hash:
                await _send_error(
                    send,
                    409,
                    "idempotency_replay",
                    "Same Idempotency-Key was used with a different request body.",
                    rid,
                )
                return
            await _send_cached(send, cached_status, cached_headers, cached_body)
            return

        # Cache miss — run inner app, capture response, store it.
        captured: _Captured = _Captured()

        async def send_capturing(message: Message) -> None:
            if message["type"] == "http.response.start":
                captured.status = int(message.get("status", 500))
                captured.headers = list(message.get("headers", []))
            elif message["type"] == "http.response.body":
                if message.get("body"):
                    captured.body_chunks.append(bytes(message["body"]))
            await send(message)

        await self.app(scope, _replayer(body, more_messages), send_capturing)

        # Only cache 2xx responses. 4xx/5xx aren't replayable safely.
        if captured.status is not None and 200 <= captured.status < 300:
            try:
                _store(
                    conn,
                    key,
                    body_hash,
                    captured.status,
                    captured.headers,
                    b"".join(captured.body_chunks),
                )
            except sqlite3.Error:
                logger.exception(
                    "idempotency_store_failed",
                    extra={"request_id": rid, "key": key},
                )


class _Captured:
    __slots__ = ("body_chunks", "headers", "status")

    def __init__(self) -> None:
        self.status: int | None = None
        self.headers: list[tuple[bytes, bytes]] = []
        self.body_chunks: list[bytes] = []


async def _drain_body(receive: Receive) -> tuple[bytes, list[Message]]:
    """Read every `http.request` message until `more_body` is False.

    Returns the concatenated body and any non-body messages we picked up
    along the way (`http.disconnect`), so we can replay them in order.
    """
    body = bytearray()
    extras: list[Message] = []
    while True:
        message = await receive()
        if message["type"] == "http.request":
            chunk = message.get("body") or b""
            if chunk:
                body.extend(chunk)
            if not message.get("more_body", False):
                return bytes(body), extras
        else:
            # http.disconnect or anything else — pass through after replay.
            extras.append(message)
            return bytes(body), extras


def _replayer(body: bytes, extras: list[Message]) -> Receive:
    sent_body = False
    extra_iter = iter(extras)

    async def replay() -> Message:
        nonlocal sent_body
        if not sent_body:
            sent_body = True
            return {"type": "http.request", "body": body, "more_body": False}
        nxt = next(extra_iter, None)
        if nxt is not None:
            return nxt
        return {"type": "http.disconnect"}

    return replay


def _request_id(scope: Scope) -> str:
    state = scope.get("state", {})
    rid = state.get("request_id") if isinstance(state, dict) else None
    return rid if isinstance(rid, str) else ""


def _conn(scope: Scope) -> sqlite3.Connection | None:
    app = scope.get("app")
    state = getattr(app, "state", None) if app is not None else None
    return getattr(state, "idempotency_conn", None) if state is not None else None


def _lookup(
    conn: sqlite3.Connection,
    key: str,
) -> tuple[str, int, list[tuple[bytes, bytes]], bytes] | None:
    row = conn.execute(
        "SELECT body_hash, status, headers, body FROM idempotency WHERE key = ?",
        (key,),
    ).fetchone()
    if row is None:
        return None
    body_hash, status, headers_json, body = row
    headers_raw = json.loads(headers_json) if headers_json else []
    headers: list[tuple[bytes, bytes]] = [
        (n.encode("latin-1"), v.encode("latin-1"))
        for n, v in headers_raw
        if isinstance(n, str) and isinstance(v, str)
    ]
    return body_hash, int(status), headers, bytes(body)


def _store(
    conn: sqlite3.Connection,
    key: str,
    body_hash: str,
    status: int,
    headers: list[tuple[bytes, bytes]],
    body: bytes,
) -> None:
    headers_filtered: list[list[str]] = [
        [n.decode("latin-1"), v.decode("latin-1")]
        for n, v in headers
        if n.lower() not in _STRIPPED_RESPONSE_HEADERS
    ]
    conn.execute(
        """
        INSERT OR REPLACE INTO idempotency
            (key, body_hash, status, headers, body, created_at)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        (key, body_hash, status, json.dumps(headers_filtered), body, int(time.time())),
    )


def _prune_expired(conn: sqlite3.Connection) -> None:
    cutoff = int(time.time()) - TTL_SECONDS
    conn.execute("DELETE FROM idempotency WHERE created_at < ?", (cutoff,))


async def _send_cached(
    send: Send,
    status: int,
    headers: list[tuple[bytes, bytes]],
    body: bytes,
) -> None:
    out_headers: list[tuple[bytes, bytes]] = list(headers)
    out_headers.append((_REPLAY_HEADER, b"true"))
    out_headers.append((b"content-length", str(len(body)).encode("latin-1")))
    await send(
        {
            "type": "http.response.start",
            "status": status,
            "headers": out_headers,
        },
    )
    await send({"type": "http.response.body", "body": body})


async def _send_error(
    send: Send,
    status: int,
    code: str,
    message: str,
    request_id: str,
) -> None:
    body = json.dumps(
        {
            "error": {
                "code": code,
                "message": message,
                "details": {},
                "request_id": request_id,
            },
        },
        ensure_ascii=False,
    ).encode("utf-8")
    await send(
        {
            "type": "http.response.start",
            "status": status,
            "headers": [
                (b"content-type", b"application/json"),
                (b"content-length", str(len(body)).encode("latin-1")),
            ],
        },
    )
    await send({"type": "http.response.body", "body": body})
