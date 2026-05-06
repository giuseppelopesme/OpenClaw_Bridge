"""Brain process entrypoint — async event-loop orchestrator.

Subscribes to ``imessage.received.{agent}`` and dispatches each
envelope to the matching handler. SIGTERM / SIGINT triggers a graceful
shutdown (close the subscriber, the bridge client, the SQLite
connection).

Dispatch is a simple ``topic -> async handler`` table. Additional
event types can populate the same table without touching the loop.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import signal
from collections.abc import Awaitable, Callable

from brains_shared import (
    BridgeClient,
    BridgeWebSocketError,
    EventEnvelope,
    EventSubscriber,
)

from agent.config import AgentConfig
from agent.context import BrainContext
from agent.handlers import imessage_received
from agent.state import State

logger = logging.getLogger("agent.main")

HandlerFn = Callable[[EventEnvelope, BrainContext], Awaitable[None]]


def _build_dispatch(agent_name: str) -> dict[str, HandlerFn]:
    """Topic → handler table, parameterised on the agent's identifier.

    Subscribed topics carry the agent's name as a suffix so the bridge
    can fan out one event to multiple agents (one envelope per
    interested brain). The brain only listens for its own variant.
    """
    return {
        f"imessage.received.{agent_name}": imessage_received.handle,
    }


def _subscribe_topic(agent_name: str) -> str:
    """Single topic this brain subscribes to (exact match, not glob)."""
    return f"imessage.received.{agent_name}"


async def run() -> int:
    cfg = AgentConfig.from_env()
    state = State(cfg.state_db_path)
    await state.open()

    stop = asyncio.Event()
    _install_signal_handlers(stop)

    try:
        async with BridgeClient(
            base_url=cfg.bridge_url,
            token=cfg.brain_token,
        ) as client:
            ctx = BrainContext(client=client, state=state, config=cfg)
            await _serve(ctx, stop)
    finally:
        await state.close()
    logger.info("brain_stopped", extra={"agent": cfg.agent_name})
    return 0


async def _serve(ctx: BrainContext, stop: asyncio.Event) -> None:
    topic = _subscribe_topic(ctx.config.agent_name)
    logger.info(
        "brain_started",
        extra={
            "agent": ctx.config.agent_name,
            "bridge_url": ctx.config.bridge_url,
            "topic": topic,
            "state_db": str(ctx.config.state_db_path),
        },
    )
    while not stop.is_set():
        try:
            await _run_subscription(ctx, stop)
        except BridgeWebSocketError as exc:
            logger.warning(
                "brain_subscription_lost",
                extra={
                    "agent": ctx.config.agent_name,
                    "reason": exc.reason,
                    "attempts": exc.attempts,
                },
            )
            # Back off briefly before reopening the subscriber. The SDK
            # has its own per-connection reconnect — this outer retry
            # handles the case where the SDK's budget was exhausted
            # (e.g. bridge fully down for several minutes).
            with contextlib.suppress(TimeoutError):
                await asyncio.wait_for(stop.wait(), timeout=5.0)


async def _run_subscription(ctx: BrainContext, stop: asyncio.Event) -> None:
    topic = _subscribe_topic(ctx.config.agent_name)
    async with EventSubscriber(
        base_url=ctx.config.bridge_url,
        token=ctx.config.brain_token,
        topic=topic,
    ) as sub:
        dispatch = _build_dispatch(ctx.config.agent_name)
        async for envelope in sub:
            if stop.is_set():
                return
            await _dispatch(envelope, ctx, dispatch)


async def _dispatch(
    envelope: EventEnvelope,
    ctx: BrainContext,
    dispatch: dict[str, HandlerFn],
) -> None:
    handler = dispatch.get(envelope.topic)
    if handler is None:
        logger.warning(
            "brain_unhandled_topic",
            extra={
                "agent": ctx.config.agent_name,
                "topic": envelope.topic,
                "event_id": envelope.event_id,
            },
        )
        return
    try:
        await handler(envelope, ctx)
    except Exception:  # noqa: BLE001 — keep the loop alive
        logger.exception(
            "brain_handler_unhandled_exception",
            extra={
                "agent": ctx.config.agent_name,
                "topic": envelope.topic,
                "event_id": envelope.event_id,
            },
        )


def _install_signal_handlers(stop: asyncio.Event) -> None:
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGTERM, signal.SIGINT):
        try:
            loop.add_signal_handler(sig, stop.set)
        except NotImplementedError:
            # Windows / sub-interpreters; not an issue on the M4 host.
            signal.signal(sig, lambda *_a: stop.set())  # noqa: PLW0108
