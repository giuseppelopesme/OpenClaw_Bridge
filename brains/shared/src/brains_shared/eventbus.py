"""WebSocket subscriber for the bridge's event bus.

Async-context-manager wrapper around ``websockets.connect`` against
``GET /v1/events/subscribe?topic=…``. Decodes each JSON frame into a
typed ``EventEnvelope`` and yields them.

### Reconnect policy

If the WebSocket closes unexpectedly while we're still in the
``async for envelope in sub:`` loop, we reconnect with bounded
exponential backoff: max 5 attempts, base 0.5s, cap 30s. Past the cap
we raise; the brain's main loop decides whether to bail or retry the
whole subscribe.

### Auth

Bearer is set on the handshake's `Authorization` header — the bridge
validates it before `accept()` per the API contract amendment from
Session 4. A wrong/missing token gets a clean WebSocket close-1008,
which surfaces here as ``BridgeWebSocketError(reason="auth")``.

### Envelope shape

We mirror ``bridge.eventbus.publisher.EventEnvelope`` rather than
importing it (boundary rule: brains never import from bridge). The
shape is documented in ``docs/event-bus.md``.
"""

from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from types import TracebackType
from typing import Any, Final, Self
from urllib.parse import quote

from websockets.asyncio.client import ClientConnection, connect
from websockets.exceptions import (
    ConnectionClosed,
    InvalidHandshake,
    InvalidStatus,
)

logger = logging.getLogger("brains_shared.eventbus")

_MAX_RECONNECT_ATTEMPTS: Final[int] = 5
_RECONNECT_BASE_S: Final[float] = 0.5
_RECONNECT_CAP_S: Final[float] = 30.0
_HANDSHAKE_TIMEOUT_S: Final[float] = 10.0


@dataclass(frozen=True)
class EventEnvelope:
    """Mirrors ``bridge.eventbus.publisher.EventEnvelope``.

    Field names match the wire envelope per ``docs/event-bus.md``;
    don't rename without updating both sides.
    """

    event_id: str
    topic: str
    published_at: str
    publisher: str
    schema_version: str
    payload: dict[str, Any] = field(default_factory=dict)


class BridgeWebSocketError(RuntimeError):
    """Raised when the WebSocket cannot be (re)established."""

    def __init__(self, *, reason: str, attempts: int = 0) -> None:
        super().__init__(f"event-bus subscribe failed: {reason} (attempts={attempts})")
        self.reason = reason
        self.attempts = attempts


class EventSubscriber:
    """Async-context-manager subscriber.

    Use as::

        async with EventSubscriber(base_url="…", token="…", topic="vault.*") as sub:
            async for envelope in sub:
                handle(envelope)

    Each iteration reads one frame; on unexpected close, reconnects
    transparently. After ``_MAX_RECONNECT_ATTEMPTS`` the iterator raises
    ``BridgeWebSocketError``.
    """

    def __init__(
        self,
        *,
        base_url: str,
        token: str,
        topic: str,
        handshake_timeout_s: float = _HANDSHAKE_TIMEOUT_S,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._token = token
        self._topic = topic
        self._handshake_timeout = handshake_timeout_s
        self._conn: ClientConnection | None = None
        self._closed: bool = False

    async def __aenter__(self) -> Self:
        await self._connect()
        return self

    async def __aexit__(
        self,
        _exc_type: type[BaseException] | None,
        _exc: BaseException | None,
        _tb: TracebackType | None,
    ) -> None:
        await self.aclose()

    async def aclose(self) -> None:
        self._closed = True
        if self._conn is not None:
            try:
                await self._conn.close()
            except (ConnectionClosed, OSError):
                logger.debug("eventbus_close_swallowed", exc_info=True)
            self._conn = None

    def __aiter__(self) -> Self:
        return self

    async def __anext__(self) -> EventEnvelope:
        if self._closed:
            raise StopAsyncIteration
        attempts = 0
        while True:
            if self._conn is None:
                await self._reconnect_or_raise(attempts)
                attempts += 1
            assert self._conn is not None
            try:
                frame = await self._conn.recv()
            except ConnectionClosed:
                logger.info(
                    "eventbus_disconnected",
                    extra={"topic": self._topic},
                )
                self._conn = None
                if attempts >= _MAX_RECONNECT_ATTEMPTS:
                    raise BridgeWebSocketError(
                        reason="reconnect_exhausted",
                        attempts=attempts,
                    ) from None
                continue
            return _decode_envelope(frame)

    async def _connect(self) -> None:
        ws_url = self._ws_url()
        try:
            self._conn = await asyncio.wait_for(
                connect(
                    ws_url,
                    additional_headers={"Authorization": f"Bearer {self._token}"},
                ),
                timeout=self._handshake_timeout,
            )
        except (TimeoutError, OSError) as exc:
            raise BridgeWebSocketError(reason=f"connect: {exc}") from exc
        except InvalidStatus as exc:
            # The bridge rejected the upgrade (auth or scope).
            status = exc.response.status_code
            raise BridgeWebSocketError(reason=f"handshake_status_{status}") from exc
        except InvalidHandshake as exc:
            raise BridgeWebSocketError(reason=f"handshake: {exc}") from exc

    async def _reconnect_or_raise(self, attempts: int) -> None:
        if attempts >= _MAX_RECONNECT_ATTEMPTS:
            raise BridgeWebSocketError(
                reason="reconnect_exhausted",
                attempts=attempts,
            )
        sleep_for = min(_RECONNECT_BASE_S * (2**attempts), _RECONNECT_CAP_S)
        if attempts > 0:
            logger.info(
                "eventbus_reconnect_sleep",
                extra={"sleep_s": sleep_for, "attempt": attempts + 1},
            )
            await asyncio.sleep(sleep_for)
        await self._connect()

    def _ws_url(self) -> str:
        scheme = "wss" if self._base_url.startswith("https://") else "ws"
        # Strip the http(s):// prefix; websockets.connect needs ws[s]://host…
        host = self._base_url.split("://", 1)[1] if "://" in self._base_url else self._base_url
        return f"{scheme}://{host}/v1/events/subscribe?topic={quote(self._topic, safe='*.')}"


def _decode_envelope(frame: str | bytes) -> EventEnvelope:
    raw = frame.decode("utf-8") if isinstance(frame, (bytes, bytearray)) else frame
    body = json.loads(raw)
    return EventEnvelope(
        event_id=str(body["event_id"]),
        topic=str(body["topic"]),
        published_at=str(body["published_at"]),
        publisher=str(body["publisher"]),
        schema_version=str(body.get("schema_version", "1")),
        payload=dict(body.get("payload", {})),
    )


__all__ = [
    "BridgeWebSocketError",
    "EventEnvelope",
    "EventSubscriber",
]


# Re-export AsyncIterator for callers that want an explicit type alias.
EnvelopeStream = AsyncIterator[EventEnvelope]
