"""Inbound iMessage handler — drives handle() against a fake bridge.

Uses httpx.MockTransport to short-circuit /v1/llm/complete,
/v1/events/publish, and /v1/agent/drafts. The brain POSTs the draft
to the bridge via brains_shared.agent.create_draft instead of storing
it locally; the bridge owns publishing draft.pending.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path
from typing import Any

import httpx
import pytest
from agent.config import AgentConfig
from agent.context import BrainContext
from agent.handlers import imessage_received
from agent.state import State
from brains_shared import EventEnvelope
from brains_shared._generated.client import AuthenticatedClient
from brains_shared.client import BridgeClient

AGENT = "agent"


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


def _llm_response(content: str) -> dict[str, Any]:
    return {
        "provider": "openrouter",
        "model": "anthropic/claude-haiku-4.5",
        "content": content,
        "usage": {"prompt_tokens": 10, "completion_tokens": 5, "cost_usd": 0.0001},
        "latency_ms": 100,
    }


def _publish_response() -> dict[str, Any]:
    return {"event_id": "evt-published", "published_at": "2026-05-02T10:00:00+00:00"}


def _draft_create_response(draft_id: str = "d-fake") -> dict[str, Any]:
    return {
        "draft_id": draft_id,
        "agent": AGENT,
        "channel": "imessage",
        "status": "pending",
        "created_at": "2026-05-02T10:00:00+00:00",
        "preview": "preview",
    }


@pytest.fixture
async def state(tmp_path: Path):
    s = State(tmp_path / "agent.state.db")
    await s.open()
    try:
        yield s
    finally:
        await s.close()


@pytest.fixture
def cfg(tmp_path: Path) -> AgentConfig:
    return AgentConfig(
        bridge_url="http://bridge.test",
        agent_name=AGENT,
        brain_token="t",
        state_db_path=tmp_path / "agent.state.db",
    )


def _envelope(*, body: str = "Hi, are you free tomorrow?") -> EventEnvelope:
    return EventEnvelope(
        event_id="evt-1",
        topic=f"imessage.received.{AGENT}",
        published_at="2026-05-02T10:00:00+00:00",
        publisher="relay.account",
        schema_version="1",
        payload={
            "from": "+39 333 1234567",
            "body": body,
            "received_at": "2026-05-02T10:00:00+00:00",
            "chat_guid": "iMessage;-;+39",
        },
    )


# -- ignore branch ---------------------------------------------------


@pytest.mark.asyncio
async def test_triage_ignore_does_not_create_draft(
    state: State,
    cfg: AgentConfig,
) -> None:
    captured: dict[str, list[str]] = {"paths": []}
    triage_count = {"calls": 0}

    def _h(req: httpx.Request) -> httpx.Response:
        captured["paths"].append(str(req.url.path))
        if str(req.url.path) == "/v1/llm/complete":
            triage_count["calls"] += 1
            return httpx.Response(
                200,
                json=_llm_response('{"action":"ignore","reason":"automated"}'),
            )
        if str(req.url.path) == "/v1/events/publish":
            return httpx.Response(202, json=_publish_response())
        if str(req.url.path) == "/v1/agent/drafts":
            return httpx.Response(201, json=_draft_create_response())
        return httpx.Response(404)

    bc = _bridge_with(_h)
    ctx = BrainContext(client=bc, state=state, config=cfg)
    await imessage_received.handle(_envelope(), ctx)

    assert triage_count["calls"] == 1
    # No draft was created — only LLM and events:publish were hit.
    assert "/v1/agent/drafts" not in captured["paths"]
    assert "/v1/events/publish" in captured["paths"]
    assert await state.is_processed("evt-1") is True


# -- draft branch ----------------------------------------------------


@pytest.mark.asyncio
async def test_triage_draft_creates_draft_via_bridge(
    state: State,
    cfg: AgentConfig,
) -> None:
    captured: dict[str, list[Any]] = {"paths": [], "drafts": []}
    llm_calls: list[str] = []

    def _h(req: httpx.Request) -> httpx.Response:
        captured["paths"].append(str(req.url.path))
        if str(req.url.path) == "/v1/llm/complete":
            body = json.loads(req.read().decode("utf-8"))
            tc = body["task_class"]
            llm_calls.append(tc)
            if tc == "triage":
                return httpx.Response(
                    200,
                    json=_llm_response('{"action":"draft","reason":"human reply"}'),
                )
            if tc == "draft":
                return httpx.Response(
                    200,
                    json=_llm_response("Yes, free at 3pm — does that work?"),
                )
            return httpx.Response(400)
        if str(req.url.path) == "/v1/agent/drafts":
            captured["drafts"].append(json.loads(req.read().decode("utf-8")))
            return httpx.Response(201, json=_draft_create_response("d-real"))
        if str(req.url.path) == "/v1/events/publish":
            return httpx.Response(202, json=_publish_response())
        return httpx.Response(404)

    bc = _bridge_with(_h)
    ctx = BrainContext(client=bc, state=state, config=cfg)
    await imessage_received.handle(_envelope(), ctx)

    assert llm_calls == ["triage", "draft"]
    assert len(captured["drafts"]) == 1
    sent = captured["drafts"][0]
    assert sent["agent"] == AGENT
    assert sent["channel"] == "imessage"
    assert sent["to_handle"] == "+39 333 1234567"
    assert "free at 3pm" in sent["body"]
    assert sent["in_reply_to_event_id"] == "evt-1"
    # Dedup row written.
    assert await state.is_processed("evt-1") is True


# -- dedup -----------------------------------------------------------


@pytest.mark.asyncio
async def test_already_processed_event_short_circuits(
    state: State,
    cfg: AgentConfig,
) -> None:
    await state.mark_processed("evt-1", f"imessage.received.{AGENT}")
    llm_called = {"called": False}

    def _h(req: httpx.Request) -> httpx.Response:
        if str(req.url.path) == "/v1/llm/complete":
            llm_called["called"] = True
        return httpx.Response(200, json=_llm_response('{"action":"ignore"}'))

    bc = _bridge_with(_h)
    ctx = BrainContext(client=bc, state=state, config=cfg)
    await imessage_received.handle(_envelope(), ctx)
    assert llm_called["called"] is False


# -- error path ------------------------------------------------------


@pytest.mark.asyncio
async def test_llm_error_publishes_task_completed_with_error(
    state: State,
    cfg: AgentConfig,
) -> None:
    captured: list[tuple[str, dict[str, Any]]] = []

    def _h(req: httpx.Request) -> httpx.Response:
        if str(req.url.path) == "/v1/llm/complete":
            return httpx.Response(
                502,
                json={
                    "error": {
                        "code": "dependency_unavailable",
                        "message": "OpenRouter timed out.",
                    },
                },
            )
        if str(req.url.path) == "/v1/events/publish":
            body = json.loads(req.read().decode("utf-8"))
            captured.append((str(body.get("topic")), body.get("payload") or {}))
            return httpx.Response(202, json=_publish_response())
        return httpx.Response(404)

    bc = _bridge_with(_h)
    ctx = BrainContext(client=bc, state=state, config=cfg)
    await imessage_received.handle(_envelope(), ctx)

    completed = [t for t in captured if t[0] == f"agent.{AGENT}.task.completed"]
    assert len(completed) == 1
    assert completed[0][1]["outcome"] == "error"
    assert "error" in completed[0][1]
    # Poison-pill: still marked processed.
    assert await state.is_processed("evt-1") is True


@pytest.mark.asyncio
async def test_create_draft_failure_publishes_error(
    state: State,
    cfg: AgentConfig,
) -> None:
    """If the bridge rejects POST /v1/agent/drafts, the brain treats the
    whole handler as a failure: task.completed outcome=error, mark
    processed."""
    captured: list[tuple[str, dict[str, Any]]] = []

    def _h(req: httpx.Request) -> httpx.Response:
        if str(req.url.path) == "/v1/llm/complete":
            body = json.loads(req.read().decode("utf-8"))
            if body["task_class"] == "triage":
                return httpx.Response(
                    200,
                    json=_llm_response('{"action":"draft","reason":"yes"}'),
                )
            return httpx.Response(200, json=_llm_response("draft body"))
        if str(req.url.path) == "/v1/agent/drafts":
            return httpx.Response(
                502,
                json={"error": {"code": "dependency_unavailable", "message": "agent_db off"}},
            )
        if str(req.url.path) == "/v1/events/publish":
            body = json.loads(req.read().decode("utf-8"))
            captured.append((str(body.get("topic")), body.get("payload") or {}))
            return httpx.Response(202, json=_publish_response())
        return httpx.Response(404)

    bc = _bridge_with(_h)
    ctx = BrainContext(client=bc, state=state, config=cfg)
    await imessage_received.handle(_envelope(), ctx)
    completed = [t for t in captured if t[0] == f"agent.{AGENT}.task.completed"]
    assert len(completed) == 1
    assert completed[0][1]["outcome"] == "error"
    assert await state.is_processed("evt-1") is True


# -- empty-body fast path -------------------------------------------


@pytest.mark.asyncio
async def test_empty_body_marks_processed_without_llm(
    state: State,
    cfg: AgentConfig,
) -> None:
    llm_called = {"called": False}

    def _h(req: httpx.Request) -> httpx.Response:
        if str(req.url.path) == "/v1/llm/complete":
            llm_called["called"] = True
            return httpx.Response(200, json=_llm_response('{"action":"ignore"}'))
        if str(req.url.path) == "/v1/events/publish":
            return httpx.Response(202, json=_publish_response())
        return httpx.Response(404)

    bc = _bridge_with(_h)
    ctx = BrainContext(client=bc, state=state, config=cfg)
    await imessage_received.handle(_envelope(body=""), ctx)
    assert llm_called["called"] is False
    assert await state.is_processed("evt-1") is True


# -- triage JSON robustness -----------------------------------------


@pytest.mark.parametrize(
    ("raw", "expected_action"),
    [
        ('{"action":"draft","reason":"x"}', "draft"),
        ('{"action":"ignore"}', "ignore"),
        ('```json\n{"action":"draft","reason":"x"}\n```', "draft"),
        ('Some prose. {"action":"draft","reason":"y"} more prose.', "draft"),
        ("garbage with no JSON at all", "ignore"),
        ('{"action":"unknown"}', "ignore"),
    ],
)
def test_triage_json_parsing(raw: str, expected_action: str) -> None:
    parsed = imessage_received._parse_triage_json(raw)  # noqa: SLF001
    assert parsed["action"] == expected_action
