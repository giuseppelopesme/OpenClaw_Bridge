"""CLU main loop — single-iteration drive against a fake subscriber.

We don't spin up a real WebSocket; we monkeypatch
``clu.main.EventSubscriber`` with a stub that yields one canned
envelope and then exits cleanly.
"""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest
from brains_shared import EventEnvelope
from clu import main as main_mod
from clu.config import CluConfig
from clu.context import BrainContext
from clu.state import State


class _FakeSubscriber:
    """Stand-in for ``brains_shared.EventSubscriber``."""

    def __init__(self, envelopes: list[EventEnvelope]) -> None:
        self._envelopes = list(envelopes)

    async def __aenter__(self) -> _FakeSubscriber:
        return self

    async def __aexit__(self, *_a: object) -> None:
        return None

    def __aiter__(self) -> _FakeSubscriber:
        return self

    async def __anext__(self) -> EventEnvelope:
        if not self._envelopes:
            raise StopAsyncIteration
        return self._envelopes.pop(0)


def _envelope(topic: str = "imessage.received.clu") -> EventEnvelope:
    return EventEnvelope(
        event_id="evt-main-1",
        topic=topic,
        published_at="2026-05-02T10:00:00+00:00",
        publisher="relay.clu",
        schema_version="1",
        payload={
            "from": "+39",
            "body": "hi",
            "received_at": "2026-05-02T10:00:00+00:00",
            "chat_guid": "g",
        },
    )


@pytest.mark.asyncio
async def test_dispatch_routes_to_handler(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """`main._dispatch` should invoke the registered handler and
    swallow its exceptions."""
    handler_called: dict[str, EventEnvelope] = {}

    async def _fake_handler(env: EventEnvelope, _ctx: BrainContext) -> None:
        handler_called["env"] = env

    monkeypatch.setitem(main_mod._DISPATCH, "imessage.received.clu", _fake_handler)

    state = State(tmp_path / "clu.state.db")
    await state.open()
    cfg = CluConfig(
        bridge_url="http://x",
        brain_token="t",
        state_db_path=tmp_path / "clu.state.db",
    )
    # We don't need a real BridgeClient — _dispatch never touches it.
    ctx = BrainContext(client=None, state=state, config=cfg)  # type: ignore[arg-type]
    try:
        await main_mod._dispatch(_envelope(), ctx)
    finally:
        await state.close()

    assert handler_called["env"].event_id == "evt-main-1"


@pytest.mark.asyncio
async def test_dispatch_unknown_topic_is_swallowed(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setattr(main_mod, "_DISPATCH", {})
    state = State(tmp_path / "clu.state.db")
    await state.open()
    cfg = CluConfig(
        bridge_url="http://x",
        brain_token="t",
        state_db_path=tmp_path / "clu.state.db",
    )
    ctx = BrainContext(client=None, state=state, config=cfg)  # type: ignore[arg-type]
    try:
        await main_mod._dispatch(_envelope(topic="something.else"), ctx)
    finally:
        await state.close()


@pytest.mark.asyncio
async def test_dispatch_swallows_handler_exception(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    async def _broken_handler(_env: EventEnvelope, _ctx: BrainContext) -> None:
        raise RuntimeError("boom")

    monkeypatch.setitem(main_mod._DISPATCH, "imessage.received.clu", _broken_handler)

    state = State(tmp_path / "clu.state.db")
    await state.open()
    cfg = CluConfig(
        bridge_url="http://x",
        brain_token="t",
        state_db_path=tmp_path / "clu.state.db",
    )
    ctx = BrainContext(client=None, state=state, config=cfg)  # type: ignore[arg-type]
    try:
        # Must not raise — the loop must keep going past handler crashes.
        await main_mod._dispatch(_envelope(), ctx)
    finally:
        await state.close()


@pytest.mark.asyncio
async def test_run_subscription_yields_then_returns_on_stop(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """End-to-end micro-drive: monkeypatch EventSubscriber with one canned
    envelope, install a no-op handler, set the stop event after the
    first yield."""
    delivered: list[str] = []

    async def _handler(env: EventEnvelope, _ctx: BrainContext) -> None:
        delivered.append(env.event_id)

    monkeypatch.setitem(main_mod._DISPATCH, "imessage.received.clu", _handler)
    monkeypatch.setattr(
        main_mod,
        "EventSubscriber",
        lambda **_kw: _FakeSubscriber([_envelope()]),
    )

    state = State(tmp_path / "clu.state.db")
    await state.open()
    cfg = CluConfig(
        bridge_url="http://x",
        brain_token="t",
        state_db_path=tmp_path / "clu.state.db",
    )
    ctx = BrainContext(client=None, state=state, config=cfg)  # type: ignore[arg-type]
    stop = asyncio.Event()
    try:
        await main_mod._run_subscription(ctx, stop)
    finally:
        await state.close()

    assert delivered == ["evt-main-1"]
