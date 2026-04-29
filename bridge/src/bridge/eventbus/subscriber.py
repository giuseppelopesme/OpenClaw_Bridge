"""Redis pubsub subscriber helper for the WebSocket route.

Wraps `Redis.pubsub` and yields decoded `EventEnvelope`s. Validates the
topic pattern against the API contract grammar before subscribing, so
callers cannot probe for arbitrary keys.

Lifecycle is `async with`:

    async with EventSubscriber(client, "vault.*") as sub:
        async for envelope in sub:
            ...

Closing the context tears down the pubsub channel cleanly.
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
from collections.abc import AsyncIterator
from types import TracebackType
from typing import Final

from redis.asyncio import Redis
from redis.asyncio.client import PubSub
from redis.exceptions import RedisError

from bridge.errors import BadRequest
from bridge.eventbus.publisher import EventEnvelope

logger = logging.getLogger("bridge.eventbus.subscriber")

# Topic grammar from `docs/event-bus.md`: dot-separated, 2–4 segments, lowercase
# alphanumerics + underscore. Subscribers may use `*` as a single-segment wildcard.
_PUBLISH_TOPIC_RE: Final[re.Pattern[str]] = re.compile(
    r"^[a-z0-9_]+(?:\.[a-z0-9_]+){1,3}$",
)
_SUBSCRIBE_PATTERN_RE: Final[re.Pattern[str]] = re.compile(
    r"^(?:\*|[a-z0-9_]+)(?:\.(?:\*|[a-z0-9_]+)){1,3}$",
)


def validate_publish_topic(topic: str) -> None:
    if not _PUBLISH_TOPIC_RE.match(topic):
        raise BadRequest(
            "Topic must be 2–4 lowercase dot-separated segments.",
            details={"topic": topic},
        )


def validate_subscribe_pattern(pattern: str) -> None:
    if not _SUBSCRIBE_PATTERN_RE.match(pattern):
        raise BadRequest(
            "Subscribe pattern must be 2–4 lowercase dot-separated segments "
            "(use `*` as a single-segment wildcard).",
            details={"topic": pattern},
        )


class EventSubscriber:
    """Async context-manager wrapping a Redis pubsub channel."""

    def __init__(self, client: Redis, pattern: str) -> None:
        validate_subscribe_pattern(pattern)
        self._client = client
        self._pattern = pattern
        self._pubsub: PubSub | None = None

    async def __aenter__(self) -> EventSubscriber:
        self._pubsub = self._client.pubsub(ignore_subscribe_messages=True)
        try:
            await self._pubsub.psubscribe(self._pattern)
        except RedisError:
            await self._safe_close()
            raise
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        await self._safe_close()

    async def _safe_close(self) -> None:
        if self._pubsub is None:
            return
        try:
            await self._pubsub.punsubscribe(self._pattern)
        except RedisError:
            logger.debug("punsubscribe_swallowed", exc_info=True)
        try:
            await self._pubsub.aclose()  # type: ignore[no-untyped-call]
        except RedisError:
            logger.debug("pubsub_aclose_swallowed", exc_info=True)
        self._pubsub = None

    async def __aiter__(self) -> AsyncIterator[EventEnvelope]:
        if self._pubsub is None:
            msg = "EventSubscriber not entered"
            raise RuntimeError(msg)
        while True:
            try:
                msg = await self._pubsub.get_message(
                    ignore_subscribe_messages=True,
                    timeout=1.0,
                )
            except RedisError as exc:
                logger.warning("pubsub_get_message_error", extra={"error": str(exc)})
                # Yield a brief sleep then retry; transport-level errors are
                # transient most of the time. The websocket route will close
                # the connection if the bridge can't recover.
                await asyncio.sleep(0.1)
                continue
            if msg is None:
                # Idle — let the websocket consumer awaiter run.
                continue
            data = msg.get("data")
            if not isinstance(data, (bytes, str)):
                continue
            try:
                envelope = EventEnvelope.from_json(data)
            except (json.JSONDecodeError, KeyError, TypeError, ValueError):
                raw = data if isinstance(data, str) else data.decode("utf-8", "replace")
                logger.warning("pubsub_decode_failed", extra={"raw": raw})
                continue
            yield envelope
