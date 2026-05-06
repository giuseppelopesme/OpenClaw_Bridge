"""brains_shared.agent — create / list / get / update wrappers."""

from __future__ import annotations

import json
from collections.abc import Callable

import httpx
import pytest
from brains_shared._generated.client import AuthenticatedClient
from brains_shared.agent import (
    AgentError,
    create_draft,
    get_draft,
    list_drafts,
    update_draft,
)
from brains_shared.client import BridgeClient


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


def _full_draft_dict(**overrides: object) -> dict[str, object]:
    base: dict[str, object] = {
        "draft_id": "d1",
        "agent": "agent",
        "channel": "imessage",
        "to_handle": "+39",
        "body": "hello",
        "status": "pending",
        "created_at": "2026-05-02T10:00:00+00:00",
        "last_modified_at": "2026-05-02T10:00:00+00:00",
        "publisher": "brain.agent",
        "in_reply_to_event_id": None,
        "preview": "hello",
        "approved_at": None,
        "approved_by": None,
        "reject_reason": None,
        "dispatch_message_id": None,
        "sent_at": None,
        "last_send_error_code": None,
        "last_send_error_message": None,
    }
    base.update(overrides)
    return base


# -- create ---------------------------------------------------------------


@pytest.mark.asyncio
async def test_create_draft_201_returns_typed() -> None:
    captured: dict[str, object] = {}

    def _h(req: httpx.Request) -> httpx.Response:
        captured["body"] = json.loads(req.read().decode("utf-8"))
        return httpx.Response(
            201,
            json={
                "draft_id": "d-new",
                "agent": "agent",
                "channel": "imessage",
                "status": "pending",
                "created_at": "2026-05-02T10:00:00+00:00",
                "preview": "hello",
            },
        )

    async with _bridge_with(_h) as bc:
        out = await create_draft(
            bc,
            agent="agent",
            to_handle="+39",
            body="hello there",
            in_reply_to_event_id="evt-x",
        )
    assert out.draft_id == "d-new"
    assert out.status == "pending"
    sent = captured["body"]
    assert isinstance(sent, dict)
    assert sent["agent"] == "agent"
    assert sent["to_handle"] == "+39"
    assert sent["body"] == "hello there"


@pytest.mark.asyncio
async def test_create_draft_non_201_raises() -> None:
    def _h(_req: httpx.Request) -> httpx.Response:
        return httpx.Response(
            502,
            json={"error": {"code": "dependency_unavailable", "message": "redis off"}},
        )

    async with _bridge_with(_h) as bc:
        with pytest.raises(AgentError) as excinfo:
            await create_draft(bc, agent="agent", to_handle="+39", body="x")
    assert excinfo.value.status == 502
    assert excinfo.value.code == "dependency_unavailable"


# -- list -----------------------------------------------------------------


@pytest.mark.asyncio
async def test_list_drafts_filters_propagated() -> None:
    captured: dict[str, str] = {}

    def _h(req: httpx.Request) -> httpx.Response:
        captured["params"] = str(req.url.params)
        return httpx.Response(
            200,
            json={"drafts": [_full_draft_dict()]},
        )

    async with _bridge_with(_h) as bc:
        drafts = await list_drafts(bc, agent="agent", status="pending", limit=10)
    assert len(drafts) == 1
    assert drafts[0].draft_id == "d1"
    params = captured["params"]
    assert "agent=agent" in params
    assert "status=pending" in params
    assert "limit=10" in params


@pytest.mark.asyncio
async def test_list_drafts_empty() -> None:
    def _h(_req: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"drafts": []})

    async with _bridge_with(_h) as bc:
        assert await list_drafts(bc) == []


# -- get ------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_draft_happy_path() -> None:
    def _h(_req: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=_full_draft_dict(draft_id="d-get", body="full"))

    async with _bridge_with(_h) as bc:
        d = await get_draft(bc, "d-get")
    assert d.draft_id == "d-get"
    assert d.body == "full"


@pytest.mark.asyncio
async def test_get_draft_404_raises() -> None:
    def _h(_req: httpx.Request) -> httpx.Response:
        return httpx.Response(
            404,
            json={"error": {"code": "not_found", "message": "missing"}},
        )

    async with _bridge_with(_h) as bc:
        with pytest.raises(AgentError) as excinfo:
            await get_draft(bc, "missing")
    assert excinfo.value.status == 404


# -- update ---------------------------------------------------------------


@pytest.mark.asyncio
async def test_update_draft_approve_round_trip() -> None:
    captured: dict[str, object] = {}

    def _h(req: httpx.Request) -> httpx.Response:
        captured["body"] = json.loads(req.read().decode("utf-8"))
        return httpx.Response(
            200,
            json=_full_draft_dict(
                status="approved",
                approved_at="2026-05-02T11:00:00+00:00",
                approved_by="giuseppe",
                dispatch_message_id="msg-xyz",
            ),
        )

    async with _bridge_with(_h) as bc:
        d = await update_draft(bc, "d1", status="approved", approved_by="giuseppe")
    assert d.status == "approved"
    assert d.approved_by == "giuseppe"
    assert d.dispatch_message_id == "msg-xyz"
    sent = captured["body"]
    assert isinstance(sent, dict)
    assert sent["status"] == "approved"
    assert sent["approved_by"] == "giuseppe"


@pytest.mark.asyncio
async def test_update_draft_reject_with_reason() -> None:
    captured: dict[str, object] = {}

    def _h(req: httpx.Request) -> httpx.Response:
        captured["body"] = json.loads(req.read().decode("utf-8"))
        return httpx.Response(
            200,
            json=_full_draft_dict(
                status="rejected",
                reject_reason="not relevant",
            ),
        )

    async with _bridge_with(_h) as bc:
        d = await update_draft(bc, "d1", status="rejected", reject_reason="not relevant")
    assert d.status == "rejected"
    assert d.reject_reason == "not relevant"


@pytest.mark.asyncio
async def test_update_draft_409_raises() -> None:
    def _h(_req: httpx.Request) -> httpx.Response:
        return httpx.Response(
            409,
            json={"error": {"code": "conflict", "message": "illegal transition"}},
        )

    async with _bridge_with(_h) as bc:
        with pytest.raises(AgentError) as excinfo:
            await update_draft(bc, "d1", status="approved")
    assert excinfo.value.status == 409
    assert excinfo.value.code == "conflict"
