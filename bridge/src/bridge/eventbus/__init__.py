"""Event bus — Redis pub/sub mediated by the bridge.

`docs/event-bus.md` is the spec. The bridge is the only Redis client; brains
and relays talk to the bus exclusively through this package via the bridge's
HTTP / WebSocket endpoints.

Two surfaces:

- `EventEnvelope` + `EventPublisher` — wrap a `redis.asyncio.Redis` instance
  and serialise the spec envelope onto a topic.
- `EventSubscriber` — pubsub helper that yields decoded envelopes; powers the
  `GET /v1/events/subscribe` WebSocket route.

Both expose a `healthcheck()` returning `ok|degraded|down` for `/v1/health`.
"""

from bridge.eventbus.publisher import (
    EventEnvelope,
    EventPublisher,
    PublishedEvent,
    build_redis_client,
)
from bridge.eventbus.subscriber import EventSubscriber

__all__ = [
    "EventEnvelope",
    "EventPublisher",
    "EventSubscriber",
    "PublishedEvent",
    "build_redis_client",
]
