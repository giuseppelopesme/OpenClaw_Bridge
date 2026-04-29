"""OpenRouter provider: happy path, missing key, HTTP error, timeout."""

from __future__ import annotations

import asyncio
from collections.abc import Callable

import httpx
import pytest
from bridge.errors import DependencyUnavailable
from bridge.providers.llm.base import LLMMessage, LLMRequest
from bridge.providers.llm.openrouter import OPENROUTER_API_BASE, OpenRouterProvider

from bridge import keychain


def _client_with(handler: Callable[[httpx.Request], httpx.Response]) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


@pytest.fixture
def request_factory() -> Callable[[], LLMRequest]:
    def make() -> LLMRequest:
        return LLMRequest(
            task_class="triage",
            messages=[LLMMessage(role="user", content="hello")],
            max_tokens=64,
            temperature=0.1,
        )

    return make


def _seed_key() -> None:
    keychain.set_credential("provider.openrouter", "fake-or-key", [])


def test_happy_path_parses_response(request_factory: Callable[[], LLMRequest]) -> None:
    _seed_key()

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.method == "POST"
        assert request.url.path.endswith("/chat/completions")
        assert request.headers["Authorization"] == "Bearer fake-or-key"
        return httpx.Response(
            200,
            json={
                "id": "chatcmpl-1",
                "model": "anthropic/claude-haiku-4.5",
                "choices": [
                    {
                        "message": {"role": "assistant", "content": "hi back"},
                        "finish_reason": "stop",
                    },
                ],
                "usage": {"prompt_tokens": 12, "completion_tokens": 4},
            },
        )

    async def run() -> None:
        async with _client_with(handler) as client:
            provider = OpenRouterProvider(client)
            resp = await provider.complete(request_factory())
        assert resp.provider == "openrouter"
        assert resp.model == "anthropic/claude-haiku-4.5"
        assert resp.content == "hi back"
        assert resp.usage.prompt_tokens == 12
        assert resp.usage.completion_tokens == 4
        # haiku rates: 12 * 1 + 4 * 5 = 32 / 1M = 0.000032
        assert resp.usage.cost_usd == 0.000032
        assert resp.latency_ms >= 0
        assert resp.extras["finish_reason"] == "stop"
        assert resp.extras["upstream_id"] == "chatcmpl-1"

    asyncio.run(run())


def test_missing_api_key_raises_dependency_unavailable(
    request_factory: Callable[[], LLMRequest],
) -> None:
    # Do NOT seed the provider key.

    async def run() -> None:
        async with _client_with(lambda r: httpx.Response(200)) as client:
            provider = OpenRouterProvider(client)
            with pytest.raises(DependencyUnavailable) as exc:
                await provider.complete(request_factory())
            assert exc.value.details["missing"] == "keychain"

    asyncio.run(run())


def test_http_error_status_surfaces_upstream_status(
    request_factory: Callable[[], LLMRequest],
) -> None:
    _seed_key()

    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(429, json={"error": {"message": "rate limited"}})

    async def run() -> None:
        async with _client_with(handler) as client:
            provider = OpenRouterProvider(client)
            with pytest.raises(DependencyUnavailable) as exc:
                await provider.complete(request_factory())
            assert exc.value.details["upstream_status"] == 429
            assert exc.value.details["timeout"] is False

    asyncio.run(run())


def test_timeout_sets_timeout_flag(request_factory: Callable[[], LLMRequest]) -> None:
    _seed_key()

    def handler(_: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("simulated")

    async def run() -> None:
        async with _client_with(handler) as client:
            provider = OpenRouterProvider(client)
            with pytest.raises(DependencyUnavailable) as exc:
                await provider.complete(request_factory())
            assert exc.value.details["timeout"] is True
            assert exc.value.details["upstream_status"] is None

    asyncio.run(run())


def test_healthcheck_ok_with_key() -> None:
    _seed_key()

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path.endswith("/models")
        return httpx.Response(200, json={"data": []})

    async def run() -> None:
        async with _client_with(handler) as client:
            provider = OpenRouterProvider(client)
            assert await provider.healthcheck() == "ok"

    asyncio.run(run())


def test_healthcheck_degraded_without_key() -> None:
    # No key seeded
    async def run() -> None:
        async with _client_with(lambda r: httpx.Response(200, json={})) as client:
            provider = OpenRouterProvider(client)
            assert await provider.healthcheck() == "degraded"

    asyncio.run(run())


def test_healthcheck_down_on_5xx() -> None:
    _seed_key()

    async def run() -> None:
        async with _client_with(lambda r: httpx.Response(503)) as client:
            provider = OpenRouterProvider(client)
            assert await provider.healthcheck() == "down"

    asyncio.run(run())


def test_api_base_is_openrouter() -> None:
    assert OPENROUTER_API_BASE.startswith("https://openrouter.ai/")
