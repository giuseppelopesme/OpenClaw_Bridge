"""Event bus unit tests — envelope shape, topic validation, publish + subscribe."""

from __future__ import annotations

import asyncio

import fakeredis.aioredis
import pytest
from bridge.errors import BadRequest, DependencyUnavailable
from bridge.eventbus import EventEnvelope, EventPublisher, EventSubscriber
from bridge.eventbus.subscriber import (
    validate_publish_topic,
    validate_subscribe_pattern,
)


def test_validate_publish_topic_accepts_two_to_four_segments() -> None:
    validate_publish_topic("vault.changed")
    validate_publish_topic("imessage.received.agent")
    validate_publish_topic("agent.agent.draft.pending")


def test_validate_publish_topic_rejects_one_segment() -> None:
    with pytest.raises(BadRequest):
        validate_publish_topic("vault")


def test_validate_publish_topic_rejects_five_segments() -> None:
    with pytest.raises(BadRequest):
        validate_publish_topic("a.b.c.d.e")


def test_validate_publish_topic_rejects_uppercase() -> None:
    with pytest.raises(BadRequest):
        validate_publish_topic("Vault.Changed")


def test_validate_publish_topic_rejects_wildcard() -> None:
    """Publishers must not push to a wildcard."""
    with pytest.raises(BadRequest):
        validate_publish_topic("vault.*")


def test_validate_subscribe_pattern_accepts_wildcard() -> None:
    validate_subscribe_pattern("vault.*")
    validate_subscribe_pattern("agent.*.task.completed")
    validate_subscribe_pattern("*.*")


def test_validate_subscribe_pattern_rejects_one_segment() -> None:
    with pytest.raises(BadRequest):
        validate_subscribe_pattern("vault")


def test_envelope_round_trips_through_json() -> None:
    env = EventEnvelope(
        event_id="evt-1",
        topic="vault.changed",
        published_at="2026-04-29T12:00:00+00:00",
        publisher="brain.agent",
        schema_version="1",
        payload={"path": "Inbox/x.md", "op": "create"},
    )
    parsed = EventEnvelope.from_json(env.to_json())
    assert parsed == env


@pytest.fixture
async def redis_fixture() -> fakeredis.aioredis.FakeRedis:
    client = fakeredis.aioredis.FakeRedis(decode_responses=False)
    yield client
    await client.aclose()


def test_publish_emits_envelope_on_topic() -> None:
    """Subscribe first, publish, assert the subscriber receives our envelope."""

    async def run() -> None:
        client = fakeredis.aioredis.FakeRedis(decode_responses=False)
        try:
            publisher = EventPublisher(client)
            received: list[EventEnvelope] = []

            async def consume() -> None:
                async with EventSubscriber(client, "vault.*") as sub:
                    async for env in sub:
                        received.append(env)
                        return

            consumer = asyncio.create_task(consume())
            # Give the subscriber time to register.
            await asyncio.sleep(0.05)
            published = await publisher.publish(
                "vault.changed",
                {"path": "Inbox/x.md", "op": "create"},
                publisher="brain.agent",
            )
            await asyncio.wait_for(consumer, timeout=2.0)

            assert len(received) == 1
            env = received[0]
            assert env.event_id == published.event_id
            assert env.topic == "vault.changed"
            assert env.publisher == "brain.agent"
            assert env.schema_version == "1"
            assert env.payload == {"path": "Inbox/x.md", "op": "create"}
        finally:
            await client.aclose()

    asyncio.run(run())


def test_publish_redis_error_raises_dependency_unavailable() -> None:
    """A closed connection surfaces as DependencyUnavailable."""

    async def run() -> None:
        client = fakeredis.aioredis.FakeRedis(decode_responses=False)
        await client.aclose()
        publisher = EventPublisher(client)
        # fakeredis allows publish on a closed client without raising — to
        # force an error we patch the publish method to raise.
        from redis.exceptions import ConnectionError as RedisConnError

        async def boom(*_args: object, **_kwargs: object) -> int:
            raise RedisConnError("simulated")

        client.publish = boom  # type: ignore[assignment]
        with pytest.raises(DependencyUnavailable):
            await publisher.publish(
                "vault.changed",
                {"path": "x"},
                publisher="brain.agent",
            )

    asyncio.run(run())


def test_subscriber_rejects_invalid_pattern() -> None:
    async def run() -> None:
        client = fakeredis.aioredis.FakeRedis(decode_responses=False)
        try:
            with pytest.raises(BadRequest):
                EventSubscriber(client, "not_valid")
        finally:
            await client.aclose()

    asyncio.run(run())


def test_publisher_healthcheck_ok_with_fakeredis() -> None:
    async def run() -> None:
        client = fakeredis.aioredis.FakeRedis(decode_responses=False)
        try:
            publisher = EventPublisher(client)
            assert await publisher.healthcheck() == "ok"
        finally:
            await client.aclose()

    asyncio.run(run())
