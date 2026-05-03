"""brains_shared.imessage.send — direct outbound (non-draft) helper."""

from __future__ import annotations

import json
from collections.abc import Callable

import httpx
import pytest
from brains_shared._generated.client import AuthenticatedClient
from brains_shared.client import BridgeClient
from brains_shared.imessage import SendError, send


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
async def test_send_happy_path_returns_message_id() -> None:
    captured: dict[str, object] = {}

    def _h(req: httpx.Request) -> httpx.Response:
        captured["body"] = json.loads(req.read().decode("utf-8"))
        return httpx.Response(
            202,
            json={"message_id": "m-123", "queued_at": "2026-05-02T15:00:00+00:00"},
        )

    async with _bridge_with(_h) as bc:
        out = await send(bc, sender="clu", to="+39", body="hi")
    assert out.message_id == "m-123"
    sent = captured["body"]
    assert isinstance(sent, dict)
    assert sent["from"] == "clu"
    assert sent["to"] == "+39"
    assert sent["body"] == "hi"


# Note: Idempotency-Key stamping is exercised by test_brains_client.py.
# The MockTransport here bypasses the retry/idempotency wrapper, so we
# don't re-test the header here — the helper's responsibility is to set
# the override ContextVar; the wrapper does the actual stamping.


@pytest.mark.asyncio
async def test_send_502_raises_send_error() -> None:
    def _h(_req: httpx.Request) -> httpx.Response:
        return httpx.Response(
            502,
            json={"error": {"code": "dependency_unavailable", "message": "redis off"}},
        )

    async with _bridge_with(_h) as bc:
        with pytest.raises(SendError) as excinfo:
            await send(bc, sender="clu", to="+39", body="hi")
    assert excinfo.value.status == 502
