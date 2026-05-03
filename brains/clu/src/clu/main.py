"""CLU process entrypoint — async event-loop orchestrator.

Subscribes to ``imessage.received.clu`` and dispatches each envelope
to the matching handler. SIGTERM / SIGINT triggers a graceful shutdown
(close the subscriber, the bridge client, the SQLite connection).

Dispatch is a simple ``topic -> async handler`` table. Sessions 10+
(TRON, FLYNN) populate the same table with more handlers; for v1 it's
just iMessage inbound.
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

from clu.config import CluConfig
from clu.context import BrainContext
from clu.handlers import imessage_received
from clu.state import State

logger = logging.getLogger("clu.main")

HandlerFn = Callable[[EventEnvelope, BrainContext], Awaitable[None]]

# Topic → handler. Lookup is exact-match against `envelope.topic`.
_DISPATCH: dict[str, HandlerFn] = {
    "imessage.received.clu": imessage_received.handle,
}

# Subscriber pattern. We use a single wildcard subscription so the
# brain can fan out to many handlers from one WebSocket later (TRON +
# FLYNN). For v1 it's effectively `imessage.received.clu`.
_SUBSCRIBE_TOPIC: str = "imessage.received.clu"


async def run() -> int:
    cfg = CluConfig.from_env()
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
    logger.info("clu_stopped")
    return 0


async def _serve(ctx: BrainContext, stop: asyncio.Event) -> None:
    logger.info(
        "clu_started",
        extra={
            "bridge_url": ctx.config.bridge_url,
            "topic": _SUBSCRIBE_TOPIC,
            "state_db": str(ctx.config.state_db_path),
        },
    )
    while not stop.is_set():
        try:
            await _run_subscription(ctx, stop)
        except BridgeWebSocketError as exc:
            logger.warning(
                "clu_subscription_lost",
                extra={"reason": exc.reason, "attempts": exc.attempts},
            )
            # Back off briefly before reopening the subscriber. The SDK
            # has its own per-connection reconnect — this outer retry
            # handles the case where the SDK's budget was exhausted
            # (e.g. bridge fully down for several minutes).
            with contextlib.suppress(TimeoutError):
                await asyncio.wait_for(stop.wait(), timeout=5.0)


async def _run_subscription(ctx: BrainContext, stop: asyncio.Event) -> None:
    async with EventSubscriber(
        base_url=ctx.config.bridge_url,
        token=ctx.config.brain_token,
        topic=_SUBSCRIBE_TOPIC,
    ) as sub:
        async for envelope in sub:
            if stop.is_set():
                return
            await _dispatch(envelope, ctx)


async def _dispatch(envelope: EventEnvelope, ctx: BrainContext) -> None:
    handler = _DISPATCH.get(envelope.topic)
    if handler is None:
        logger.warning(
            "clu_unhandled_topic",
            extra={"topic": envelope.topic, "event_id": envelope.event_id},
        )
        return
    try:
        await handler(envelope, ctx)
    except Exception:  # noqa: BLE001 — keep the loop alive
        logger.exception(
            "clu_handler_unhandled_exception",
            extra={"topic": envelope.topic, "event_id": envelope.event_id},
        )


def _install_signal_handlers(stop: asyncio.Event) -> None:
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGTERM, signal.SIGINT):
        try:
            loop.add_signal_handler(sig, stop.set)
        except NotImplementedError:
            # Windows / sub-interpreters; not an issue on the M4 host.
            signal.signal(sig, lambda *_a: stop.set())  # noqa: PLW0108
