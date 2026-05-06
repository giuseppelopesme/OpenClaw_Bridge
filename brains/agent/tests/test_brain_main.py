"""Brain main loop — single-iteration drive against a fake subscriber.

We don't spin up a real WebSocket; we monkeypatch
``agent.main.EventSubscriber`` with a stub that yields one canned
envelope and then exits cleanly.
"""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest
from agent import main as main_mod
from agent.config import AgentConfig
from agent.context import BrainContext
from agent.state import State
from brains_shared import EventEnvelope

AGENT = "agent"


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


def _envelope(topic: str = f"imessage.received.{AGENT}") -> EventEnvelope:
    return EventEnvelope(
        event_id="evt-main-1",
        topic=topic,
        published_at="2026-05-02T10:00:00+00:00",
        publisher="relay.account",
        schema_version="1",
        payload={
            "from": "+39",
            "body": "hi",
            "received_at": "2026-05-02T10:00:00+00:00",
            "chat_guid": "g",
        },
    )


def _cfg(tmp_path: Path) -> AgentConfig:
    return AgentConfig(
        bridge_url="http://x",
        agent_name=AGENT,
        brain_token="t",
        state_db_path=tmp_path / "agent.state.db",
    )


@pytest.mark.asyncio
async def test_dispatch_routes_to_handler(tmp_path: Path) -> None:
    """``main._dispatch`` should invoke the registered handler and
    swallow its exceptions."""
    handler_called: dict[str, EventEnvelope] = {}

    async def _fake_handler(env: EventEnvelope, _ctx: BrainContext) -> None:
        handler_called["env"] = env

    state = State(tmp_path / "agent.state.db")
    await state.open()
    cfg = _cfg(tmp_path)
    # We don't need a real BridgeClient — _dispatch never touches it.
    ctx = BrainContext(client=None, state=state, config=cfg)  # type: ignore[arg-type]
    dispatch = {f"imessage.received.{AGENT}": _fake_handler}
    try:
        await main_mod._dispatch(_envelope(), ctx, dispatch)
    finally:
        await state.close()

    assert handler_called["env"].event_id == "evt-main-1"


@pytest.mark.asyncio
async def test_dispatch_unknown_topic_is_swallowed(tmp_path: Path) -> None:
    state = State(tmp_path / "agent.state.db")
    await state.open()
    cfg = _cfg(tmp_path)
    ctx = BrainContext(client=None, state=state, config=cfg)  # type: ignore[arg-type]
    try:
        await main_mod._dispatch(_envelope(topic="something.else"), ctx, {})
    finally:
        await state.close()


@pytest.mark.asyncio
async def test_dispatch_swallows_handler_exception(tmp_path: Path) -> None:
    async def _broken_handler(_env: EventEnvelope, _ctx: BrainContext) -> None:
        raise RuntimeError("boom")

    state = State(tmp_path / "agent.state.db")
    await state.open()
    cfg = _cfg(tmp_path)
    ctx = BrainContext(client=None, state=state, config=cfg)  # type: ignore[arg-type]
    dispatch = {f"imessage.received.{AGENT}": _broken_handler}
    try:
        # Must not raise — the loop must keep going past handler crashes.
        await main_mod._dispatch(_envelope(), ctx, dispatch)
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

    # Override the dispatch table builder so our handler is wired up
    # for the agent name under test.
    monkeypatch.setattr(
        main_mod,
        "_build_dispatch",
        lambda agent_name: {f"imessage.received.{agent_name}": _handler},
    )
    monkeypatch.setattr(
        main_mod,
        "EventSubscriber",
        lambda **_kw: _FakeSubscriber([_envelope()]),
    )

    state = State(tmp_path / "agent.state.db")
    await state.open()
    cfg = _cfg(tmp_path)
    ctx = BrainContext(client=None, state=state, config=cfg)  # type: ignore[arg-type]
    stop = asyncio.Event()
    try:
        await main_mod._run_subscription(ctx, stop)
    finally:
        await state.close()

    assert delivered == ["evt-main-1"]


def test_subscribe_topic_uses_agent_name() -> None:
    assert main_mod._subscribe_topic("agent") == "imessage.received.agent"
    assert main_mod._subscribe_topic("custom") == "imessage.received.custom"
