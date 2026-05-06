"""POST /v1/events/publish + GET /v1/events/subscribe (WebSocket).

The full end-to-end loop is covered: publish, subscriber receives, format
matches the spec envelope. Auth + scope rejections, body validation, and
the unconfigured-Redis path round it out.
"""

from __future__ import annotations

import json

from _support import TokenFixture
from bridge.eventbus import EventEnvelope
from fastapi.testclient import TestClient

from bridge import keychain  # noqa: F401 — keeps fixture order deterministic

PUBLISHER_TOKEN = "dev-token-publisher"
SUBSCRIBER_TOKEN = "dev-token-subscriber"
NO_SCOPE_TOKEN = "dev-token-empty"

PUBLISHER_HEADERS = {"Authorization": f"Bearer {PUBLISHER_TOKEN}"}


def _seed_event_actors(tokens: list[TokenFixture]) -> None:
    """Add a publisher + subscriber actor to the existing fake Keychain."""
    _ = tokens
    keychain.set_credential(
        "brain.events_pub",
        PUBLISHER_TOKEN,
        ["events:publish"],
    )
    keychain.set_credential(
        "brain.events_sub",
        SUBSCRIBER_TOKEN,
        ["events:subscribe"],
    )


def _refresh(client: TestClient) -> None:
    client.app.state.token_store.refresh()  # type: ignore[attr-defined]


def test_events_publish_happy_path(
    client: TestClient,
    tokens: list[TokenFixture],
) -> None:
    _seed_event_actors(tokens)
    _refresh(client)

    resp = client.post(
        "/v1/events/publish",
        json={
            "topic": "vault.changed",
            "payload": {"path": "Inbox/x.md", "op": "create"},
        },
        headers=PUBLISHER_HEADERS,
    )
    assert resp.status_code == 202
    body = resp.json()
    assert "event_id" in body
    assert "published_at" in body


def test_events_publish_requires_scope(
    client: TestClient,
    tokens: list[TokenFixture],
) -> None:
    _ = tokens
    resp = client.post(
        "/v1/events/publish",
        json={"topic": "vault.changed", "payload": {}},
        headers={"Authorization": f"Bearer {NO_SCOPE_TOKEN}"},
    )
    assert resp.status_code == 403
    assert resp.json()["error"]["code"] == "forbidden_scope"


def test_events_publish_validates_topic_segments(
    client: TestClient,
    tokens: list[TokenFixture],
) -> None:
    _seed_event_actors(tokens)
    _refresh(client)

    resp = client.post(
        "/v1/events/publish",
        json={"topic": "single", "payload": {}},
        headers=PUBLISHER_HEADERS,
    )
    assert resp.status_code == 400
    assert resp.json()["error"]["code"] == "bad_request"


def test_events_publish_rejects_uppercase(
    client: TestClient,
    tokens: list[TokenFixture],
) -> None:
    _seed_event_actors(tokens)
    _refresh(client)
    resp = client.post(
        "/v1/events/publish",
        json={"topic": "Vault.Changed", "payload": {}},
        headers=PUBLISHER_HEADERS,
    )
    assert resp.status_code == 400


def test_events_subscribe_websocket_round_trip(
    client: TestClient,
    tokens: list[TokenFixture],
) -> None:
    """Open a WS, publish via the HTTP route, assert the WS frame matches."""
    _seed_event_actors(tokens)
    _refresh(client)

    with client.websocket_connect(
        "/v1/events/subscribe?topic=vault.*",
        headers={"Authorization": f"Bearer {SUBSCRIBER_TOKEN}"},
    ) as ws:
        # The WS server uses redis psubscribe; allow a short delay so the
        # subscription is registered before we publish.
        publish_resp = client.post(
            "/v1/events/publish",
            json={
                "topic": "vault.changed",
                "payload": {"path": "Inbox/y.md", "op": "append"},
            },
            headers=PUBLISHER_HEADERS,
        )
        assert publish_resp.status_code == 202
        published = publish_resp.json()

        raw = ws.receive_text()
        envelope = EventEnvelope.from_json(raw)
        assert envelope.topic == "vault.changed"
        assert envelope.event_id == published["event_id"]
        assert envelope.publisher == "brain.events_pub"
        assert envelope.payload == {"path": "Inbox/y.md", "op": "append"}


def test_events_subscribe_rejects_missing_token(
    client: TestClient,
) -> None:
    """No Authorization → server closes immediately."""
    from starlette.websockets import WebSocketDisconnect

    try:
        with client.websocket_connect("/v1/events/subscribe?topic=vault.*"):
            pass  # pragma: no cover - should not reach
    except WebSocketDisconnect as exc:
        assert exc.code == 1008
        return
    raise AssertionError("expected WebSocketDisconnect")


def test_events_subscribe_rejects_missing_scope(
    client: TestClient,
    tokens: list[TokenFixture],
) -> None:
    from starlette.websockets import WebSocketDisconnect

    _seed_event_actors(tokens)
    _refresh(client)
    try:
        with client.websocket_connect(
            "/v1/events/subscribe?topic=vault.*",
            headers={"Authorization": f"Bearer {NO_SCOPE_TOKEN}"},
        ):
            pass  # pragma: no cover
    except WebSocketDisconnect as exc:
        assert exc.code == 1008
        return
    raise AssertionError("expected WebSocketDisconnect")


def test_events_subscribe_rejects_invalid_topic(
    client: TestClient,
    tokens: list[TokenFixture],
) -> None:
    from starlette.websockets import WebSocketDisconnect

    _seed_event_actors(tokens)
    _refresh(client)
    try:
        with client.websocket_connect(
            "/v1/events/subscribe?topic=NOT_VALID",
            headers={"Authorization": f"Bearer {SUBSCRIBER_TOKEN}"},
        ):
            pass  # pragma: no cover
    except WebSocketDisconnect as exc:
        assert exc.code == 1008
        return
    raise AssertionError("expected WebSocketDisconnect")


def test_vault_write_publishes_vault_changed(
    client: TestClient,
    tokens: list[TokenFixture],
) -> None:
    """A successful vault write triggers a publish on `vault.changed`."""
    _ = tokens
    # The default brain.agent fixture lacks events:subscribe — promote it.
    keychain.set_credential(
        "brain.agent",
        "dev-token-agent",
        ["llm:call", "vault:read", "vault:write", "events:subscribe"],
    )
    _refresh(client)

    with client.websocket_connect(
        "/v1/events/subscribe?topic=vault.*",
        headers={"Authorization": "Bearer dev-token-agent"},
    ) as ws:
        write_resp = client.post(
            "/v1/vault/write",
            json={
                "path": "Inbox/event-test.md",
                "mode": "create",
                "content": "hi\n",
            },
            headers={"Authorization": "Bearer dev-token-agent"},
        )
        assert write_resp.status_code == 201

        raw = ws.receive_text()
        env = EventEnvelope.from_json(raw)
        assert env.topic == "vault.changed"
        assert env.payload["path"] == "Inbox/event-test.md"
        assert env.payload["op"] == "create"
        assert env.publisher == "brain.agent"


def test_events_publish_redis_unavailable_returns_502(
    client: TestClient,
    tokens: list[TokenFixture],
) -> None:
    _seed_event_actors(tokens)
    _refresh(client)
    # Simulate "Redis not configured" by clearing the publisher.
    client.app.state.event_publisher = None  # type: ignore[attr-defined]
    resp = client.post(
        "/v1/events/publish",
        json={"topic": "vault.changed", "payload": {}},
        headers=PUBLISHER_HEADERS,
    )
    assert resp.status_code == 502
    assert resp.json()["error"]["code"] == "dependency_unavailable"


def test_event_envelope_payload_roundtrips_complex_types(
    client: TestClient,
    tokens: list[TokenFixture],
) -> None:
    """Nested dicts/lists in payloads survive the JSON round trip."""
    _seed_event_actors(tokens)
    _refresh(client)
    payload = {
        "nested": {"a": 1, "b": [1, 2, 3]},
        "unicode": "héllo",
    }
    with client.websocket_connect(
        "/v1/events/subscribe?topic=agent.*.draft.pending",
        headers={"Authorization": f"Bearer {SUBSCRIBER_TOKEN}"},
    ) as ws:
        resp = client.post(
            "/v1/events/publish",
            json={"topic": "agent.agent.draft.pending", "payload": payload},
            headers=PUBLISHER_HEADERS,
        )
        assert resp.status_code == 202
        env = EventEnvelope.from_json(ws.receive_text())
        assert env.payload == payload
        # Ensure unicode survived the encode/decode cycle.
        decoded = json.loads(env.to_json())
        assert decoded["payload"]["unicode"] == "héllo"
