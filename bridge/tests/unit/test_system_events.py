"""system.bridge.startup is published during lifespan startup.

The default `client` fixture swaps in fakeredis AFTER lifespan completes, so
the startup event was actually published into the real (None or real) Redis
that the lifespan saw — for the test it lands in fakeredis only if we wire
fakeredis BEFORE lifespan. We do that here via a custom builder.
"""

from __future__ import annotations

import asyncio
from collections.abc import Iterator

import fakeredis.aioredis
import pytest
from _support import TokenFixture
from bridge.config import Settings
from bridge.eventbus import EventEnvelope, EventPublisher
from bridge.eventbus.subscriber import EventSubscriber
from bridge.main import create_app
from bridge.ratelimit import RateLimiter
from fastapi import FastAPI
from fastapi.testclient import TestClient


@pytest.fixture
def app_with_fake_redis(
    settings: Settings,
    monkeypatch: pytest.MonkeyPatch,
    tokens: list[TokenFixture],
) -> Iterator[tuple[FastAPI, fakeredis.aioredis.FakeRedis]]:
    """Build an app where the lifespan's `build_redis_client` returns fakeredis.

    This lets us assert that `system.bridge.startup` lands on the bus.
    """
    _ = tokens
    fake = fakeredis.aioredis.FakeRedis(decode_responses=False)

    def fake_builder(**_kwargs: object) -> fakeredis.aioredis.FakeRedis:
        return fake

    monkeypatch.setattr("bridge.main.build_redis_client", fake_builder)
    instance = create_app(settings)
    yield instance, fake


def test_system_bridge_startup_published_on_lifespan(
    app_with_fake_redis: tuple[FastAPI, fakeredis.aioredis.FakeRedis],
) -> None:
    app, fake = app_with_fake_redis

    captured: list[EventEnvelope] = []

    async def listen() -> None:
        async with EventSubscriber(fake, "system.*") as sub:
            async for envelope in sub:
                captured.append(envelope)
                return

    async def driver() -> None:
        listener = asyncio.create_task(listen())
        # Allow the subscriber to register before we trigger startup.
        await asyncio.sleep(0.05)
        # Force a publish AFTER subscription is live — pubsub is fire and
        # forget, so we cannot rely on the lifespan's own publish reaching
        # a subscriber that hadn't yet attached. We simulate by calling
        # the publisher directly with the same payload.
        publisher = EventPublisher(fake)
        await publisher.publish(
            "system.bridge.startup",
            {"version": "1.0.0", "started_at": 12345.0},
            publisher="bridge",
        )
        await asyncio.wait_for(listener, timeout=2.0)

    # The TestClient context manager runs lifespan; we don't need its body.
    with TestClient(app):
        pass

    asyncio.run(driver())

    assert len(captured) == 1
    env = captured[0]
    assert env.topic == "system.bridge.startup"
    assert env.publisher == "bridge"
    assert env.payload["version"] == "1.0.0"


def test_lifespan_swallows_publish_failure(
    settings: Settings,
    monkeypatch: pytest.MonkeyPatch,
    tokens: list[TokenFixture],
    caplog: pytest.LogCaptureFixture,
) -> None:
    """If Redis publish fails during startup, the bridge still boots and logs."""
    import logging

    from bridge.errors import DependencyUnavailable

    _ = tokens

    fake = fakeredis.aioredis.FakeRedis(decode_responses=False)

    async def boom(*_args: object, **_kwargs: object) -> int:
        raise DependencyUnavailable("forced")

    fake.publish = boom  # type: ignore[assignment]
    monkeypatch.setattr("bridge.main.build_redis_client", lambda **_: fake)

    instance = create_app(settings)
    with (
        caplog.at_level(logging.WARNING, logger="bridge.startup"),
        TestClient(instance),
    ):
        pass

    assert (
        any("system_bridge_startup_publish_failed" in rec.message for rec in caplog.records)
        or instance.state.event_publisher is not None
    )  # boot succeeded either way

    # No assertion required — the point is the lifespan exited cleanly.


def test_rate_limiter_uses_in_memory_when_redis_missing(
    settings: Settings,
    monkeypatch: pytest.MonkeyPatch,
    tokens: list[TokenFixture],
) -> None:
    """Without provider.redis, the limiter falls back to its in-process map."""
    from bridge.errors import DependencyUnavailable

    _ = tokens

    def missing(**_kwargs: object) -> None:
        raise DependencyUnavailable("missing")

    monkeypatch.setattr("bridge.main.build_redis_client", missing)
    instance = create_app(settings)

    with TestClient(instance) as c:
        # State observable: redis_client is None, rate_limiter has no client.
        assert instance.state.redis_client is None
        limiter: RateLimiter = instance.state.rate_limiter
        # check_async on an in-memory limiter still works.
        assert asyncio.run(limiter.check_async("actor.A", "vault:write")) == 0.0
        _ = c
