"""Redis pub/sub publisher — stamps the spec envelope onto a topic.

Per `docs/event-bus.md`, every event is a JSON object with this envelope:

    {
      "event_id": "uuid",
      "topic": "imessage.received.clu",
      "published_at": "2026-04-29T10:00:00Z",
      "publisher": "relay.clu",
      "schema_version": "1",
      "payload": { ... topic-specific ... }
    }

The publisher takes the `topic`, `payload`, and `publisher` (the actor) and
stamps the rest. Returns a `PublishedEvent` with the assigned event_id and
published_at so callers (the events route) can echo them back.

Network errors raise `DependencyUnavailable` (502) — the same convention
the LLM routes use.
"""

from __future__ import annotations

import asyncio
import json
import logging
import uuid
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from typing import Any, Final, Literal

from redis.asyncio import Redis
from redis.exceptions import RedisError

from bridge import keychain
from bridge.errors import DependencyUnavailable

logger = logging.getLogger("bridge.eventbus.publisher")

REDIS_KEYCHAIN_ACTOR: Final[str] = "provider.redis"
SCHEMA_VERSION: Final[str] = "1"

DepStatus = Literal["ok", "degraded", "down"]


@dataclass(frozen=True)
class EventEnvelope:
    event_id: str
    topic: str
    published_at: str
    publisher: str
    schema_version: str
    payload: dict[str, Any]

    def to_json(self) -> str:
        return json.dumps(asdict(self), ensure_ascii=False, default=str)

    @classmethod
    def from_json(cls, raw: str | bytes) -> EventEnvelope:
        if isinstance(raw, bytes):
            raw = raw.decode("utf-8")
        body = json.loads(raw)
        return cls(
            event_id=str(body["event_id"]),
            topic=str(body["topic"]),
            published_at=str(body["published_at"]),
            publisher=str(body["publisher"]),
            schema_version=str(body["schema_version"]),
            payload=dict(body.get("payload", {})),
        )


@dataclass(frozen=True)
class PublishedEvent:
    """Bookkeeping returned to the route after a successful publish."""

    event_id: str
    published_at: str


def build_redis_client(
    *,
    host: str = "127.0.0.1",
    port: int = 6379,
    db: int = 0,
) -> Redis:
    """Construct a `redis.asyncio.Redis` bound to the Keychain `provider.redis`
    password. Raises `DependencyUnavailable` if the password is missing.

    Connection is lazy — Redis is contacted on the first command, not here.
    Health probes therefore fail loudly only when actually used."""
    cred = keychain.get_credential(REDIS_KEYCHAIN_ACTOR)
    if cred is None or not cred.token:
        raise DependencyUnavailable(
            "Redis password is not configured.",
            details={"missing": "keychain", "actor": REDIS_KEYCHAIN_ACTOR},
        )
    return Redis(
        host=host,
        port=port,
        db=db,
        password=cred.token,
        decode_responses=False,
        socket_connect_timeout=2.0,
        socket_timeout=5.0,
    )


class EventPublisher:
    """Thin wrapper around `Redis.publish` that stamps the spec envelope."""

    def __init__(self, client: Redis) -> None:
        self._client = client

    async def publish(
        self,
        topic: str,
        payload: dict[str, Any],
        *,
        publisher: str,
    ) -> PublishedEvent:
        envelope = EventEnvelope(
            event_id=str(uuid.uuid4()),
            topic=topic,
            published_at=datetime.now(UTC).isoformat(),
            publisher=publisher,
            schema_version=SCHEMA_VERSION,
            payload=payload,
        )
        body = envelope.to_json().encode("utf-8")
        try:
            await self._client.publish(topic, body)
        except RedisError as exc:
            raise DependencyUnavailable(
                "Redis publish failed.",
                details={"topic": topic, "error": str(exc)},
            ) from exc
        return PublishedEvent(
            event_id=envelope.event_id,
            published_at=envelope.published_at,
        )

    async def healthcheck(self) -> DepStatus:
        try:
            ping_call = self._client.ping()
            # redis-py's stubs type ping() as `Awaitable[bool] | bool`. The
            # asyncio client always returns an awaitable; the union covers
            # the sync sibling. Coerce so wait_for is happy.
            if not isinstance(ping_call, bool):
                pong = await asyncio.wait_for(ping_call, timeout=2.0)
            else:
                pong = ping_call
        except (RedisError, TimeoutError, OSError):
            return "down"
        return "ok" if pong else "degraded"

    async def aclose(self) -> None:
        try:
            await self._client.aclose()
        except RedisError:  # pragma: no cover - best-effort shutdown
            logger.debug("redis_aclose_swallowed", exc_info=True)
