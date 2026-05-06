"""brains_shared.events.publish_event — POST /v1/events/publish wrapper."""

from __future__ import annotations

import json
from collections.abc import Callable

import httpx
import pytest
from brains_shared._generated.client import AuthenticatedClient
from brains_shared.client import BridgeClient
from brains_shared.events import EventPublishError, publish_event


def _bridge_with(
    handler: Callable[[httpx.Request], httpx.Response],
) -> BridgeClient:
    bc = BridgeClient(base_url="http://bridge.test", token="t")
    mock_httpx = httpx.AsyncClient(
        base_url="http://bridge.test",
        timeout=2.0,
        transport=httpx.MockTransport(handler),
        headers={"Authorization": "Bearer t"},
    )
    bc._inner = AuthenticatedClient(  # noqa: SLF001
        base_url="http://bridge.test",
        token="t",
    ).set_async_httpx_client(mock_httpx)
    bc._httpx = mock_httpx  # noqa: SLF001
    return bc


@pytest.mark.asyncio
async def test_publish_event_happy_path() -> None:
    captured: dict[str, object] = {}

    def _h(req: httpx.Request) -> httpx.Response:
        captured["body"] = json.loads(req.read().decode("utf-8"))
        return httpx.Response(
            202,
            json={
                "event_id": "evt-1",
                "published_at": "2026-05-02T10:00:00+00:00",
            },
        )

    bc = _bridge_with(_h)
    out = await publish_event(
        bc,
        topic="agent.agent.draft.pending",
        payload={"draft_id": "abc", "channel": "imessage", "preview": "hi"},
    )
    body = captured["body"]
    assert isinstance(body, dict)
    assert body["topic"] == "agent.agent.draft.pending"
    assert body["payload"] == {"draft_id": "abc", "channel": "imessage", "preview": "hi"}
    assert out.event_id == "evt-1"
    assert out.published_at == "2026-05-02T10:00:00+00:00"


@pytest.mark.asyncio
async def test_publish_event_400_raises_with_envelope() -> None:
    def _h(_req: httpx.Request) -> httpx.Response:
        return httpx.Response(
            400,
            json={"error": {"code": "bad_request", "message": "topic invalid"}},
        )

    bc = _bridge_with(_h)
    with pytest.raises(EventPublishError) as excinfo:
        await publish_event(bc, topic="BAD.UPPER.CASE", payload={})
    assert excinfo.value.status == 400
    assert excinfo.value.code == "bad_request"


@pytest.mark.asyncio
async def test_publish_event_omits_payload_when_none() -> None:
    captured: dict[str, object] = {}

    def _h(req: httpx.Request) -> httpx.Response:
        captured["body"] = json.loads(req.read().decode("utf-8"))
        return httpx.Response(
            202,
            json={"event_id": "x", "published_at": "2026-05-02T10:00:00+00:00"},
        )

    bc = _bridge_with(_h)
    await publish_event(bc, topic="agent.agent.task.completed")
    body = captured["body"]
    assert isinstance(body, dict)
    # `payload` may be absent (UNSET serialises out) or present-and-empty;
    # either is fine for the bridge. Confirm it's not surfacing junk.
    if "payload" in body:
        assert body["payload"] == {} or body["payload"] is None
