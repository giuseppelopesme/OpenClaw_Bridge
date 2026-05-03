"""BridgeClient — exercises the three calls + retry policy via httpx.MockTransport."""

from __future__ import annotations

from collections.abc import Callable

import httpx
import pytest
from relay.bridge_client import BridgeClient, BridgeClientError


def _client_with(handler: Callable[[httpx.Request], httpx.Response]) -> BridgeClient:
    bc = BridgeClient(base_url="http://bridge.test", token="t")
    bc._client.close()  # noqa: SLF001 — replace the auto-built client
    bc._client = httpx.Client(  # noqa: SLF001
        base_url="http://bridge.test",
        timeout=2.0,
        headers={"Authorization": "Bearer t"},
        transport=httpx.MockTransport(handler),
    )
    return bc


def test_post_inbound_happy_path() -> None:
    captured: dict[str, object] = {}

    def _h(req: httpx.Request) -> httpx.Response:
        captured["path"] = req.url.path
        captured["body"] = req.read()
        captured["request_id"] = req.headers.get("X-Request-ID")
        return httpx.Response(200, json={"received": True, "event_id": "evt-1"})

    with _client_with(_h) as bc:
        out = bc.post_inbound(
            agent="clu",
            sender="+39",
            body="hi",
            received_at="2026-05-02T10:00:00+00:00",
            chat_guid="g",
        )

    assert out["event_id"] == "evt-1"
    assert captured["path"] == "/v1/imessage/inbound"
    assert captured["request_id"]


def test_get_outbox_happy_path_returns_job() -> None:
    def _h(_req: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={"message_id": "abc", "to": "+39", "body": "hi"},
        )

    with _client_with(_h) as bc:
        job = bc.get_outbox(agent="clu", timeout_s=1)
    assert job is not None
    assert job["message_id"] == "abc"


def test_get_outbox_returns_none_on_204() -> None:
    def _h(_req: httpx.Request) -> httpx.Response:
        return httpx.Response(204)

    with _client_with(_h) as bc:
        job = bc.get_outbox(agent="clu", timeout_s=1)
    assert job is None


def test_post_sent_includes_status_and_optional_fields() -> None:
    captured: dict[str, object] = {}

    def _h(req: httpx.Request) -> httpx.Response:
        captured["body"] = req.read().decode("utf-8")
        return httpx.Response(200, json={"acknowledged": True, "event_id": "evt-2"})

    with _client_with(_h) as bc:
        bc.post_sent(
            agent="clu",
            message_id="m1",
            to="+39",
            body="hi",
            status="failed",
            error_code="buddy_not_found",
            error_message="not on iMessage",
        )
    body = str(captured["body"])
    assert '"status":"failed"' in body
    assert '"error_code":"buddy_not_found"' in body
    assert '"error_message":"not on iMessage"' in body


def test_4xx_does_not_retry() -> None:
    calls = 0

    def _h(_req: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(400, json={"error": {"code": "bad_request"}})

    with _client_with(_h) as bc, pytest.raises(BridgeClientError) as excinfo:
        bc.post_inbound(
            agent="clu",
            sender="+39",
            body="x",
            received_at="2026-05-02T10:00:00+00:00",
            chat_guid="g",
        )
    assert calls == 1
    assert excinfo.value.status == 400


def test_5xx_retries_then_raises() -> None:
    calls = 0

    def _h(_req: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(503, text="bad")

    with _client_with(_h) as bc, pytest.raises(BridgeClientError) as excinfo:
        bc.post_inbound(
            agent="clu",
            sender="+39",
            body="x",
            received_at="2026-05-02T10:00:00+00:00",
            chat_guid="g",
        )
    assert calls == 3  # _MAX_ATTEMPTS
    assert excinfo.value.status == 503


def test_5xx_then_success_returns_payload() -> None:
    state = {"calls": 0}

    def _h(_req: httpx.Request) -> httpx.Response:
        state["calls"] += 1
        if state["calls"] == 1:
            return httpx.Response(502)
        return httpx.Response(200, json={"received": True, "event_id": "evt-X"})

    with _client_with(_h) as bc:
        out = bc.post_inbound(
            agent="clu",
            sender="+39",
            body="x",
            received_at="2026-05-02T10:00:00+00:00",
            chat_guid="g",
        )
    assert out["event_id"] == "evt-X"
    assert state["calls"] == 2
