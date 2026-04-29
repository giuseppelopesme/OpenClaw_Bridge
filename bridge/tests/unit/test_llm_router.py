"""LLMRouter: hint-based selection + task_class routing under auto."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass

import pytest
from bridge.errors import DependencyUnavailable
from bridge.providers.llm.base import LLMMessage, LLMRequest, LLMResponse, LLMUsage
from bridge.providers.llm.router import LLMRouter


@dataclass
class _FakeProvider:
    name: str
    last_request: LLMRequest | None = None

    async def complete(self, request: LLMRequest) -> LLMResponse:
        self.last_request = request
        return LLMResponse(
            provider=self.name,
            model=f"{self.name}/model",
            content="ok",
            usage=LLMUsage(prompt_tokens=1, completion_tokens=1, cost_usd=0.0),
            latency_ms=1,
        )

    async def healthcheck(self) -> str:
        return "ok"


def _request(task_class: str, hint: str = "auto") -> LLMRequest:
    return LLMRequest(
        task_class=task_class,  # type: ignore[arg-type]
        provider_hint=hint,  # type: ignore[arg-type]
        messages=[LLMMessage(role="user", content="x")],
    )


def test_hint_openrouter_always_openrouter() -> None:
    openrouter = _FakeProvider("openrouter")
    local = _FakeProvider("local")
    r = LLMRouter(openrouter=openrouter, local=local)

    asyncio.run(r.complete(_request("triage", "openrouter")))
    assert openrouter.last_request is not None
    assert local.last_request is None


def test_hint_local_uses_local_when_available() -> None:
    openrouter = _FakeProvider("openrouter")
    local = _FakeProvider("local")
    r = LLMRouter(openrouter=openrouter, local=local)

    asyncio.run(r.complete(_request("reason", "local")))
    assert local.last_request is not None
    assert openrouter.last_request is None


def test_hint_local_raises_when_local_absent() -> None:
    openrouter = _FakeProvider("openrouter")
    r = LLMRouter(openrouter=openrouter, local=None)

    with pytest.raises(DependencyUnavailable):
        asyncio.run(r.complete(_request("triage", "local")))


def test_auto_with_local_routes_triage_classify_to_local() -> None:
    openrouter = _FakeProvider("openrouter")
    local = _FakeProvider("local")
    r = LLMRouter(openrouter=openrouter, local=local)

    asyncio.run(r.complete(_request("triage")))
    asyncio.run(r.complete(_request("classify")))

    assert local.last_request is not None
    assert openrouter.last_request is None


def test_auto_routes_reason_draft_summarise_to_openrouter() -> None:
    openrouter = _FakeProvider("openrouter")
    local = _FakeProvider("local")
    r = LLMRouter(openrouter=openrouter, local=local)

    for tc in ("reason", "draft", "summarise"):
        asyncio.run(r.complete(_request(tc)))
    assert openrouter.last_request is not None
    assert local.last_request is None


def test_auto_falls_through_to_openrouter_when_local_absent() -> None:
    """Session 3 stub: with no local provider, auto routes everything to openrouter."""
    openrouter = _FakeProvider("openrouter")
    r = LLMRouter(openrouter=openrouter, local=None)

    for tc in ("triage", "classify", "reason", "draft", "summarise"):
        asyncio.run(r.complete(_request(tc)))
    assert openrouter.last_request is not None
