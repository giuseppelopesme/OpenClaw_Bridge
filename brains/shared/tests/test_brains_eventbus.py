"""EventSubscriber — happy path, decode, reconnect, exhaustion.

We monkeypatch `brains_shared.eventbus.connect` (the
`websockets.asyncio.client.connect` re-export) so tests don't need a
real WebSocket server. Each test plants a `_FakeConn` (or a sequence
of them) that yields canned frames and then closes.
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator, Awaitable, Callable
from typing import Any

import pytest
from brains_shared import eventbus as eventbus_module
from brains_shared.eventbus import (
    BridgeWebSocketError,
    EventEnvelope,
    EventSubscriber,
)
from websockets.exceptions import ConnectionClosed, InvalidStatus


class _FakeConn:
    """Minimal stand-in for `websockets.asyncio.client.ClientConnection`."""

    def __init__(
        self,
        *,
        frames: list[str | bytes],
        close_after: bool = False,
    ) -> None:
        self._frames = list(frames)
        self._close_after = close_after
        self._closed = False

    async def recv(self) -> str | bytes:
        if self._closed:
            raise ConnectionClosed(rcvd=None, sent=None)
        if not self._frames:
            self._closed = True
            if self._close_after:
                raise ConnectionClosed(rcvd=None, sent=None)
            # No more frames — block forever to mimic a quiet socket.
            await asyncio.sleep(3600)
            raise AssertionError("unreachable")
        return self._frames.pop(0)

    async def close(self) -> None:
        self._closed = True


def _envelope_frame(
    *,
    topic: str,
    payload: dict[str, Any] | None = None,
    event_id: str = "evt-1",
) -> str:
    return json.dumps(
        {
            "event_id": event_id,
            "topic": topic,
            "published_at": "2026-05-02T10:00:00+00:00",
            "publisher": "test",
            "schema_version": "1",
            "payload": payload or {},
        },
    )


def _patch_connect(
    monkeypatch: pytest.MonkeyPatch,
    factory: Callable[..., Awaitable[_FakeConn]],
) -> None:
    monkeypatch.setattr(eventbus_module, "connect", factory)


@pytest.mark.asyncio
async def test_subscribe_yields_decoded_envelopes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    conn = _FakeConn(
        frames=[
            _envelope_frame(topic="vault.changed", payload={"path": "Inbox/x.md"}),
        ],
    )

    async def _connect(*_a: Any, **_kw: Any) -> _FakeConn:
        return conn

    _patch_connect(monkeypatch, _connect)

    async with EventSubscriber(
        base_url="http://bridge.test",
        token="t",
        topic="vault.*",
    ) as sub:
        ait: AsyncIterator[EventEnvelope] = aiter(sub)
        env = await asyncio.wait_for(anext(ait), timeout=1.0)

    assert env.topic == "vault.changed"
    assert env.payload == {"path": "Inbox/x.md"}
    assert env.event_id == "evt-1"


@pytest.mark.asyncio
async def test_subscribe_reconnects_after_unexpected_close(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """First conn yields one frame then closes; second conn yields another."""
    first = _FakeConn(
        frames=[_envelope_frame(topic="vault.changed", event_id="evt-1")],
        close_after=True,
    )
    second = _FakeConn(
        frames=[_envelope_frame(topic="vault.changed", event_id="evt-2")],
    )
    conns = iter([first, second])

    async def _connect(*_a: Any, **_kw: Any) -> _FakeConn:
        return next(conns)

    _patch_connect(monkeypatch, _connect)

    async with EventSubscriber(
        base_url="http://bridge.test",
        token="t",
        topic="vault.*",
    ) as sub:
        ait = aiter(sub)
        e1 = await asyncio.wait_for(anext(ait), timeout=1.0)
        e2 = await asyncio.wait_for(anext(ait), timeout=2.0)

    assert e1.event_id == "evt-1"
    assert e2.event_id == "evt-2"


@pytest.mark.asyncio
async def test_subscribe_exhausts_reconnects_and_raises(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Every connection closes immediately; after _MAX_RECONNECT_ATTEMPTS
    we raise BridgeWebSocketError."""
    monkeypatch.setattr(eventbus_module, "_RECONNECT_BASE_S", 0.001)

    async def _connect(*_a: Any, **_kw: Any) -> _FakeConn:
        return _FakeConn(frames=[], close_after=True)

    _patch_connect(monkeypatch, _connect)

    async with EventSubscriber(
        base_url="http://bridge.test",
        token="t",
        topic="vault.*",
    ) as sub:
        ait = aiter(sub)
        with pytest.raises(BridgeWebSocketError):
            await asyncio.wait_for(anext(ait), timeout=2.0)


@pytest.mark.asyncio
async def test_handshake_status_failure_is_reported(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Bad token surfaces as InvalidStatus → BridgeWebSocketError."""

    class _Resp:
        status_code = 1008

    async def _connect(*_a: Any, **_kw: Any) -> _FakeConn:
        raise InvalidStatus(_Resp())

    _patch_connect(monkeypatch, _connect)

    with pytest.raises(BridgeWebSocketError) as excinfo:
        async with EventSubscriber(
            base_url="http://bridge.test",
            token="bad",
            topic="vault.*",
        ):
            pass
    assert "1008" in excinfo.value.reason


@pytest.mark.asyncio
async def test_subscribe_url_includes_topic_query(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, str] = {}

    async def _connect(url: str, *_a: Any, **kwargs: Any) -> _FakeConn:
        captured["url"] = url
        captured["headers"] = json.dumps(dict(kwargs.get("additional_headers", {})))
        return _FakeConn(frames=[])

    _patch_connect(monkeypatch, _connect)

    async with EventSubscriber(
        base_url="http://bridge.test",
        token="t",
        topic="vault.*",
    ):
        pass

    assert "ws://bridge.test/v1/events/subscribe?topic=vault.*" in captured["url"]
    assert "Authorization" in captured["headers"]
    assert "Bearer t" in captured["headers"]
