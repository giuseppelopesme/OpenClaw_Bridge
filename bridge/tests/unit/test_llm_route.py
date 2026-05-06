"""POST /v1/llm/complete — happy path, scope, rate limit, provider failure, telemetry."""

from __future__ import annotations

import sqlite3

import pytest
from _support import TokenFixture
from bridge.errors import DependencyUnavailable
from bridge.providers.llm.base import LLMRequest, LLMResponse, LLMUsage
from bridge.providers.llm.router import LLMRouter
from bridge.ratelimit import spec_for
from fastapi.testclient import TestClient

AUTH_OK = {"Authorization": "Bearer dev-token-agent"}


class _FakeProvider:
    name = "openrouter"

    def __init__(self, response: LLMResponse | Exception) -> None:
        self._response = response
        self.calls: list[LLMRequest] = []

    async def complete(self, request: LLMRequest) -> LLMResponse:
        self.calls.append(request)
        if isinstance(self._response, Exception):
            raise self._response
        return self._response

    async def healthcheck(self) -> str:
        return "ok"


def _wire_fake(client: TestClient, response: LLMResponse | Exception) -> _FakeProvider:
    fake = _FakeProvider(response)
    client.app.state.llm_router = LLMRouter(openrouter=fake, local=None)  # type: ignore[arg-type, attr-defined]
    return fake


def _success_response() -> LLMResponse:
    return LLMResponse(
        provider="openrouter",
        model="anthropic/claude-haiku-4.5",
        content="hello back",
        usage=LLMUsage(prompt_tokens=10, completion_tokens=5, cost_usd=0.000035),
        latency_ms=42,
    )


def _llm_payload(task_class: str = "triage") -> dict[str, object]:
    return {
        "task_class": task_class,
        "messages": [{"role": "user", "content": "hi"}],
    }


def test_llm_complete_happy_path_returns_documented_shape(
    client: TestClient,
    tokens: list[TokenFixture],  # noqa: ARG001
) -> None:
    _wire_fake(client, _success_response())
    resp = client.post("/v1/llm/complete", json=_llm_payload(), headers=AUTH_OK)
    assert resp.status_code == 200
    body = resp.json()
    assert body == {
        "provider": "openrouter",
        "model": "anthropic/claude-haiku-4.5",
        "content": "hello back",
        "usage": {"prompt_tokens": 10, "completion_tokens": 5, "cost_usd": 0.000035},
        "latency_ms": 42,
    }


def test_llm_complete_writes_telemetry_row_on_success(
    client: TestClient,
    tokens: list[TokenFixture],  # noqa: ARG001
) -> None:
    _wire_fake(client, _success_response())
    resp = client.post("/v1/llm/complete", json=_llm_payload(), headers=AUTH_OK)
    assert resp.status_code == 200

    conn: sqlite3.Connection = client.app.state.telemetry_conn  # type: ignore[attr-defined]
    rows = conn.execute(
        "SELECT actor, task_class, provider, model, prompt_tokens, completion_tokens, "
        "cost_usd, latency_ms, status, error_code FROM llm_calls",
    ).fetchall()
    assert len(rows) == 1
    actor, task_class, provider, model, p_t, c_t, cost, latency, status, err = rows[0]
    assert actor == "brain.agent"
    assert task_class == "triage"
    assert provider == "openrouter"
    assert model == "anthropic/claude-haiku-4.5"
    assert p_t == 10
    assert c_t == 5
    assert cost == pytest.approx(0.000035)
    assert latency == 42
    assert status == "success"
    assert err is None


def test_llm_complete_writes_telemetry_row_on_provider_failure(
    client: TestClient,
    tokens: list[TokenFixture],  # noqa: ARG001
) -> None:
    err = DependencyUnavailable(
        "OpenRouter HTTP error.",
        details={"timeout": False, "upstream_status": 500, "model": "x", "latency_ms": 12},
    )
    _wire_fake(client, err)
    resp = client.post("/v1/llm/complete", json=_llm_payload(), headers=AUTH_OK)
    assert resp.status_code == 502
    assert resp.json()["error"]["code"] == "dependency_unavailable"

    conn: sqlite3.Connection = client.app.state.telemetry_conn  # type: ignore[attr-defined]
    rows = conn.execute(
        "SELECT status, error_code, latency_ms FROM llm_calls",
    ).fetchall()
    assert len(rows) == 1
    status, error_code, latency = rows[0]
    assert status == "error"
    assert error_code == "dependency_unavailable"
    assert latency == 12


def test_llm_complete_marks_timeout_status(
    client: TestClient,
    tokens: list[TokenFixture],  # noqa: ARG001
) -> None:
    err = DependencyUnavailable(
        "OpenRouter timed out.",
        details={"timeout": True, "upstream_status": None, "model": "y", "latency_ms": 30000},
    )
    _wire_fake(client, err)
    resp = client.post("/v1/llm/complete", json=_llm_payload(), headers=AUTH_OK)
    assert resp.status_code == 502

    conn: sqlite3.Connection = client.app.state.telemetry_conn  # type: ignore[attr-defined]
    status, latency = conn.execute(
        "SELECT status, latency_ms FROM llm_calls",
    ).fetchone()
    assert status == "timeout"
    assert latency == 30000


def test_llm_complete_requires_llm_call_scope(
    client: TestClient,
    tokens: list[TokenFixture],  # noqa: ARG001
) -> None:
    """dev-token-empty has no scopes."""
    resp = client.post(
        "/v1/llm/complete",
        json=_llm_payload(),
        headers={"Authorization": "Bearer dev-token-empty"},
    )
    assert resp.status_code == 403
    assert resp.json()["error"]["code"] == "forbidden_scope"


def test_llm_complete_rate_limited_after_burst(
    client: TestClient,
    tokens: list[TokenFixture],  # noqa: ARG001
) -> None:
    _wire_fake(client, _success_response())
    spec = spec_for("llm:call")
    for _ in range(spec.burst):
        resp = client.post("/v1/llm/complete", json=_llm_payload(), headers=AUTH_OK)
        assert resp.status_code == 200
    final = client.post("/v1/llm/complete", json=_llm_payload(), headers=AUTH_OK)
    assert final.status_code == 429
    assert final.json()["error"]["code"] == "rate_limited"
    assert int(final.headers["Retry-After"]) >= 1


def test_llm_complete_validates_request_body(
    client: TestClient,
    tokens: list[TokenFixture],  # noqa: ARG001
) -> None:
    """Bad task_class → 422 envelope, not a 500."""
    resp = client.post(
        "/v1/llm/complete",
        json={"task_class": "bogus", "messages": [{"role": "user", "content": "x"}]},
        headers=AUTH_OK,
    )
    assert resp.status_code == 422
    assert resp.json()["error"]["code"] == "validation_failed"
