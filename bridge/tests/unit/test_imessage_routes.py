"""iMessage HTTP endpoints — send / inbound / outbox / sent.

End-to-end against the test client's fakeredis. Exercises the queue
round-trip (RPUSH via /send → BLPOP via /outbox), event publishing
(/inbound and /sent both emit topic envelopes the test subscribes to),
and the standard auth/scope/rate-limit stack.
"""

from __future__ import annotations

import asyncio
import json

import pytest
from _support import TokenFixture
from bridge.eventbus.subscriber import EventSubscriber
from fastapi.testclient import TestClient

SEND = {"Authorization": "Bearer dev-token-imessage-send"}
RELAY = {"Authorization": "Bearer dev-token-imessage-relay"}


# -- POST /v1/imessage/send -----------------------------------------------


def test_send_enqueues_to_redis_list(
    client: TestClient,
    tokens: list[TokenFixture],  # noqa: ARG001
) -> None:
    resp = client.post(
        "/v1/imessage/send",
        json={"from": "agent", "to": "+390000000001", "body": "hi", "service": "iMessage"},
        headers=SEND,
    )
    assert resp.status_code == 202
    body = resp.json()
    assert body["message_id"]
    assert body["queued_at"]

    # Inspect the queue directly via the fakeredis client.
    redis = client.app.state.redis_client

    async def _read() -> bytes | None:
        return await redis.lpop("imessage:outbound:agent")

    raw = asyncio.run(_read())
    assert raw is not None
    job = json.loads(raw.decode("utf-8"))
    assert job["from"] == "agent"
    assert job["to"] == "+390000000001"
    assert job["body"] == "hi"
    assert job["message_id"] == body["message_id"]


def test_send_requires_send_scope(client: TestClient) -> None:
    resp = client.post(
        "/v1/imessage/send",
        json={"from": "agent", "to": "+39", "body": "x"},
        headers={"Authorization": "Bearer dev-token-empty"},
    )
    assert resp.status_code == 403


def test_send_redis_unavailable_returns_502(
    client: TestClient,
    tokens: list[TokenFixture],  # noqa: ARG001
) -> None:
    client.app.state.redis_client = None
    resp = client.post(
        "/v1/imessage/send",
        json={"from": "agent", "to": "+39", "body": "x"},
        headers=SEND,
    )
    assert resp.status_code == 502
    assert resp.json()["error"]["code"] == "dependency_unavailable"


def test_send_invalid_sender_returns_422(
    client: TestClient,
    tokens: list[TokenFixture],  # noqa: ARG001
) -> None:
    """Senders must match the agent-name regex (lowercase alnum/_, 1-32
    chars) or be the literal "main"; uppercase + hyphens fail the
    pattern."""
    resp = client.post(
        "/v1/imessage/send",
        json={"from": "Stranger-Sender", "to": "+39", "body": "x"},
        headers=SEND,
    )
    assert resp.status_code == 422


def test_send_rate_limit_exhausts_after_burst(
    client: TestClient,
    tokens: list[TokenFixture],  # noqa: ARG001
) -> None:
    # Burst is 5 per the spec; the 6th call within the burst window must 429.
    payload = {"from": "agent", "to": "+39", "body": "ping"}
    last_status = 0
    for _ in range(7):
        resp = client.post("/v1/imessage/send", json=payload, headers=SEND)
        last_status = resp.status_code
        if last_status == 429:
            break
    assert last_status == 429
    assert resp.headers.get("Retry-After") is not None


# -- POST /v1/imessage/inbound --------------------------------------------


@pytest.mark.asyncio
async def test_inbound_publishes_received_event(
    client: TestClient,
    tokens: list[TokenFixture],  # noqa: ARG001
) -> None:
    redis = client.app.state.redis_client

    async with EventSubscriber(redis, "imessage.received.agent") as sub:
        # Submit the inbound POST in a task; the subscriber must receive
        # the corresponding envelope.

        async def _post() -> None:
            await asyncio.to_thread(
                lambda: client.post(
                    "/v1/imessage/inbound",
                    json={
                        "agent": "agent",
                        "from": "+39 333 1234567",
                        "body": "hello",
                        "received_at": "2026-05-02T10:00:00+00:00",
                        "chat_guid": "iMessage;-;+39",
                    },
                    headers=RELAY,
                ),
            )

        post_task = asyncio.create_task(_post())
        envelope = await asyncio.wait_for(anext(aiter(sub)), timeout=2.0)
        await post_task

    assert envelope.topic == "imessage.received.agent"
    assert envelope.payload["from"] == "+39 333 1234567"
    assert envelope.payload["body"] == "hello"
    assert envelope.payload["chat_guid"] == "iMessage;-;+39"


def test_inbound_requires_relay_scope(client: TestClient) -> None:
    resp = client.post(
        "/v1/imessage/inbound",
        json={
            "agent": "agent",
            "from": "+39",
            "body": "x",
            "received_at": "2026-05-02T10:00:00+00:00",
            "chat_guid": "g",
        },
        headers={"Authorization": "Bearer dev-token-empty"},
    )
    assert resp.status_code == 403


def test_inbound_malformed_agent_returns_422(
    client: TestClient,
    tokens: list[TokenFixture],  # noqa: ARG001
) -> None:
    """Agent must match the well-formed-identifier regex; uppercase +
    digit-leading + hyphen all fail the pattern."""
    resp = client.post(
        "/v1/imessage/inbound",
        json={
            "agent": "1-Bogus",
            "from": "+39",
            "body": "x",
            "received_at": "2026-05-02T10:00:00+00:00",
            "chat_guid": "g",
        },
        headers=RELAY,
    )
    assert resp.status_code == 422


# -- GET /v1/imessage/outbox ----------------------------------------------


def test_outbox_returns_queued_job(
    client: TestClient,
    tokens: list[TokenFixture],  # noqa: ARG001
) -> None:
    # Enqueue via /send first.
    enqueue = client.post(
        "/v1/imessage/send",
        json={"from": "agent", "to": "+39", "body": "hi"},
        headers=SEND,
    )
    assert enqueue.status_code == 202
    expected_id = enqueue.json()["message_id"]

    resp = client.get(
        "/v1/imessage/outbox?agent=agent&timeout_s=2",
        headers=RELAY,
    )
    assert resp.status_code == 200
    job = resp.json()
    assert job["message_id"] == expected_id
    assert job["from"] == "agent"
    assert job["to"] == "+39"


def test_outbox_returns_204_on_timeout(
    client: TestClient,
    tokens: list[TokenFixture],  # noqa: ARG001
) -> None:
    # Empty queue + tiny timeout → 204 with no body.
    resp = client.get(
        "/v1/imessage/outbox?agent=agent&timeout_s=1",
        headers=RELAY,
    )
    assert resp.status_code == 204
    assert not resp.content


def test_outbox_requires_relay_scope(client: TestClient) -> None:
    resp = client.get(
        "/v1/imessage/outbox?agent=agent&timeout_s=0",
        headers={"Authorization": "Bearer dev-token-empty"},
    )
    assert resp.status_code == 403


def test_outbox_malformed_agent_returns_422(
    client: TestClient,
    tokens: list[TokenFixture],  # noqa: ARG001
) -> None:
    """Outbox query param must match the agent-name regex."""
    resp = client.get("/v1/imessage/outbox?agent=Bad-Agent", headers=RELAY)
    assert resp.status_code == 422


# -- POST /v1/imessage/sent ------------------------------------------------


@pytest.mark.asyncio
async def test_sent_success_publishes_imessage_sent(
    client: TestClient,
    tokens: list[TokenFixture],  # noqa: ARG001
) -> None:
    redis = client.app.state.redis_client

    async with EventSubscriber(redis, "imessage.sent.agent") as sub:

        async def _post() -> None:
            await asyncio.to_thread(
                lambda: client.post(
                    "/v1/imessage/sent",
                    json={
                        "agent": "agent",
                        "message_id": "abc-123",
                        "to": "+39",
                        "body": "hello",
                        "status": "success",
                        "sent_at": "2026-05-02T11:00:00+00:00",
                    },
                    headers=RELAY,
                ),
            )

        task = asyncio.create_task(_post())
        envelope = await asyncio.wait_for(anext(aiter(sub)), timeout=2.0)
        await task

    assert envelope.topic == "imessage.sent.agent"
    assert envelope.payload["message_id"] == "abc-123"
    assert envelope.payload["sent_at"] == "2026-05-02T11:00:00+00:00"


@pytest.mark.asyncio
async def test_sent_failed_publishes_imessage_send_failed(
    client: TestClient,
    tokens: list[TokenFixture],  # noqa: ARG001
) -> None:
    redis = client.app.state.redis_client

    async with EventSubscriber(redis, "imessage.send.failed.agent") as sub:

        async def _post() -> None:
            await asyncio.to_thread(
                lambda: client.post(
                    "/v1/imessage/sent",
                    json={
                        "agent": "agent",
                        "message_id": "abc-123",
                        "to": "+39",
                        "body": "hello",
                        "status": "failed",
                        "error_code": "buddy_not_found",
                        "error_message": "Recipient is not on iMessage.",
                    },
                    headers=RELAY,
                ),
            )

        task = asyncio.create_task(_post())
        envelope = await asyncio.wait_for(anext(aiter(sub)), timeout=2.0)
        await task

    assert envelope.topic == "imessage.send.failed.agent"
    assert envelope.payload["error_code"] == "buddy_not_found"
    assert envelope.payload["error_message"] == "Recipient is not on iMessage."


def test_sent_requires_relay_scope(client: TestClient) -> None:
    resp = client.post(
        "/v1/imessage/sent",
        json={
            "agent": "agent",
            "message_id": "x",
            "to": "+39",
            "body": "x",
            "status": "success",
        },
        headers={"Authorization": "Bearer dev-token-empty"},
    )
    assert resp.status_code == 403
