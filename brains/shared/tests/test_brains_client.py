"""BridgeClient — Idempotency-Key auto-stamping + 429 retry policy."""

from __future__ import annotations

from collections.abc import Callable

import httpx
import pytest
from brains_shared.client import (
    BridgeClient,
    BridgeClientError,
    _RetryAndIdempotencyTransport,  # type: ignore[attr-defined]  # private but tested
    idempotency_key,
)


def _client_with(
    handler: Callable[[httpx.Request], httpx.Response],
    *,
    max_retries: int = 3,
) -> BridgeClient:
    """Build a BridgeClient whose transport wraps the supplied handler."""
    bc = BridgeClient(base_url="http://bridge.test", token="t")
    # Replace the underlying transport with a MockTransport wrapped by
    # the same retry/idempotency layer the real client has.
    bc._transport = _RetryAndIdempotencyTransport(  # noqa: SLF001
        httpx.MockTransport(handler),
        max_retries=max_retries,
    )
    bc._httpx = httpx.AsyncClient(  # noqa: SLF001
        base_url="http://bridge.test",
        timeout=2.0,
        transport=bc._transport,
        headers={"Authorization": "Bearer t"},
    )
    return bc


@pytest.mark.asyncio
async def test_idempotency_key_auto_stamped_on_post() -> None:
    captured: dict[str, str] = {}

    def _h(req: httpx.Request) -> httpx.Response:
        captured["key"] = req.headers.get("Idempotency-Key", "")
        return httpx.Response(200, json={"ok": True})

    async with _client_with(_h) as bc:
        await bc._httpx.post("/v1/anything", json={})  # noqa: SLF001
    assert captured["key"]
    # UUIDs are 36 chars (8-4-4-4-12).
    assert len(captured["key"]) == 36


@pytest.mark.asyncio
async def test_idempotency_key_caller_override_wins() -> None:
    captured: dict[str, str] = {}

    def _h(req: httpx.Request) -> httpx.Response:
        captured["key"] = req.headers.get("Idempotency-Key", "")
        return httpx.Response(200)

    async with _client_with(_h) as bc, idempotency_key("daily-2026-05-02"):
        await bc._httpx.post("/v1/anything", json={})  # noqa: SLF001
    assert captured["key"] == "daily-2026-05-02"


@pytest.mark.asyncio
async def test_idempotency_key_not_added_to_get_requests() -> None:
    captured: dict[str, str] = {}

    def _h(req: httpx.Request) -> httpx.Response:
        captured["key"] = req.headers.get("Idempotency-Key", "")
        return httpx.Response(200)

    async with _client_with(_h) as bc:
        await bc._httpx.get("/v1/anything")  # noqa: SLF001
    assert captured["key"] == ""


@pytest.mark.asyncio
async def test_429_then_success_returns_200() -> None:
    state = {"calls": 0}

    def _h(_req: httpx.Request) -> httpx.Response:
        state["calls"] += 1
        if state["calls"] == 1:
            return httpx.Response(429, headers={"Retry-After": "0.1"})
        return httpx.Response(200, json={"ok": True})

    async with _client_with(_h) as bc:
        resp = await bc._httpx.post("/v1/anything", json={})  # noqa: SLF001
    assert resp.status_code == 200
    assert state["calls"] == 2


@pytest.mark.asyncio
async def test_429_after_max_retries_raises() -> None:
    def _h(_req: httpx.Request) -> httpx.Response:
        return httpx.Response(429, headers={"Retry-After": "0.05"})

    async with _client_with(_h, max_retries=2) as bc:
        with pytest.raises(BridgeClientError) as excinfo:
            await bc._httpx.post("/v1/anything", json={})  # noqa: SLF001
    assert excinfo.value.status == 429


@pytest.mark.asyncio
async def test_429_uses_same_idempotency_key_across_retries() -> None:
    seen_keys: list[str] = []

    def _h(req: httpx.Request) -> httpx.Response:
        seen_keys.append(req.headers.get("Idempotency-Key", ""))
        if len(seen_keys) < 2:
            return httpx.Response(429, headers={"Retry-After": "0.05"})
        return httpx.Response(200)

    async with _client_with(_h) as bc:
        await bc._httpx.post("/v1/anything", json={})  # noqa: SLF001
    assert len(seen_keys) == 2
    assert seen_keys[0] == seen_keys[1]


@pytest.mark.asyncio
async def test_429_with_retry_after_above_cap_raises() -> None:
    def _h(_req: httpx.Request) -> httpx.Response:
        # 999 seconds is way past the default 30s cap.
        return httpx.Response(429, headers={"Retry-After": "999"})

    async with _client_with(_h) as bc:
        with pytest.raises(BridgeClientError) as excinfo:
            await bc._httpx.post("/v1/anything", json={})  # noqa: SLF001
    assert excinfo.value.retry_after == 999.0
