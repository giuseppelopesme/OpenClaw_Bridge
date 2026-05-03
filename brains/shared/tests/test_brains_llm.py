"""LLM task_class shortcuts — verify each shortcut sends the right
task_class string and forwards optional kwargs.
"""

from __future__ import annotations

import json
from collections.abc import Callable

import httpx
import pytest
from brains_shared._generated.client import AuthenticatedClient
from brains_shared.client import BridgeClient
from brains_shared.llm import (
    LLMError,
    classify,
    complete,
    draft,
    reason,
    summarise,
    triage,
)


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


def _ok_response(req: httpx.Request) -> httpx.Response:
    return httpx.Response(
        200,
        json={
            "provider": "openrouter",
            "model": "anthropic/claude-haiku-4.5",
            "content": "hello world",
            "usage": {"prompt_tokens": 5, "completion_tokens": 2, "cost_usd": 0.0001},
            "latency_ms": 200,
        },
    )


@pytest.mark.asyncio
async def test_complete_sends_task_class_and_messages() -> None:
    captured: dict[str, object] = {}

    def _h(req: httpx.Request) -> httpx.Response:
        captured["body"] = json.loads(req.read().decode("utf-8"))
        return _ok_response(req)

    bc = _bridge_with(_h)
    resp = await complete(
        bc,
        task_class="reason",
        messages=[{"role": "user", "content": "what is 2+2?"}],
        temperature=0.0,
        max_tokens=42,
    )
    body = captured["body"]
    assert isinstance(body, dict)
    assert body["task_class"] == "reason"
    assert body["messages"] == [{"role": "user", "content": "what is 2+2?"}]
    assert body["temperature"] == 0.0
    assert body["max_tokens"] == 42
    assert resp.content == "hello world"


@pytest.mark.parametrize(
    ("shortcut", "expected_task_class"),
    [
        (triage, "triage"),
        (classify, "classify"),
        (reason, "reason"),
        (draft, "draft"),
        (summarise, "summarise"),
    ],
)
@pytest.mark.asyncio
async def test_each_shortcut_sets_correct_task_class(
    shortcut: Callable[..., object],
    expected_task_class: str,
) -> None:
    captured: dict[str, object] = {}

    def _h(req: httpx.Request) -> httpx.Response:
        captured["body"] = json.loads(req.read().decode("utf-8"))
        return _ok_response(req)

    bc = _bridge_with(_h)
    await shortcut(bc, messages=[{"role": "user", "content": "hi"}])  # type: ignore[arg-type]
    body = captured["body"]
    assert isinstance(body, dict)
    assert body["task_class"] == expected_task_class


@pytest.mark.asyncio
async def test_shortcut_forwards_provider_and_model_hints() -> None:
    captured: dict[str, object] = {}

    def _h(req: httpx.Request) -> httpx.Response:
        captured["body"] = json.loads(req.read().decode("utf-8"))
        return _ok_response(req)

    bc = _bridge_with(_h)
    await draft(
        bc,
        messages=[{"role": "user", "content": "hi"}],
        provider_hint="openrouter",
        model_hint="anthropic/claude-sonnet-4.5",
        response_format="json",
    )
    body = captured["body"]
    assert isinstance(body, dict)
    assert body["provider_hint"] == "openrouter"
    assert body["model_hint"] == "anthropic/claude-sonnet-4.5"
    assert body["response_format"] == "json"


@pytest.mark.asyncio
async def test_unknown_role_rejected() -> None:
    bc = _bridge_with(_ok_response)
    with pytest.raises(ValueError, match="role"):
        await triage(bc, messages=[{"role": "elf", "content": "x"}])


@pytest.mark.asyncio
async def test_502_maps_to_llm_error() -> None:
    def _h(_req: httpx.Request) -> httpx.Response:
        return httpx.Response(
            502,
            json={
                "error": {
                    "code": "dependency_unavailable",
                    "message": "OpenRouter timed out.",
                },
            },
        )

    bc = _bridge_with(_h)
    with pytest.raises(LLMError) as excinfo:
        await reason(bc, messages=[{"role": "user", "content": "x"}])
    assert excinfo.value.status == 502
    assert excinfo.value.code == "dependency_unavailable"
