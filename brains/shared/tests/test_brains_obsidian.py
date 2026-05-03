"""Vault helpers — read / write / append round-trips against MockTransport."""

from __future__ import annotations

import json
from collections.abc import Callable

import httpx
import pytest
from brains_shared._generated.client import AuthenticatedClient
from brains_shared.client import BridgeClient
from brains_shared.obsidian import (
    VaultError,
    append_to_inbox,
    read_page,
    write_page,
)


def _bridge_with(
    handler: Callable[[httpx.Request], httpx.Response],
) -> BridgeClient:
    """Build a BridgeClient whose generated AuthenticatedClient uses the
    given mock transport."""
    bc = BridgeClient(base_url="http://bridge.test", token="t")
    mock_httpx = httpx.AsyncClient(
        base_url="http://bridge.test",
        timeout=2.0,
        transport=httpx.MockTransport(handler),
        headers={"Authorization": "Bearer t"},
    )
    # Pin the inner generated client's httpx instance to the mock so
    # `asyncio_detailed` calls hit our handler.
    bc._inner = AuthenticatedClient(  # noqa: SLF001
        base_url="http://bridge.test",
        token="t",
    ).set_async_httpx_client(mock_httpx)
    bc._httpx = mock_httpx  # noqa: SLF001 — keep aclose() consistent
    return bc


@pytest.mark.asyncio
async def test_read_page_happy_path() -> None:
    captured: dict[str, str] = {}

    def _h(req: httpx.Request) -> httpx.Response:
        captured["path"] = str(req.url.params.get("path"))
        return httpx.Response(
            200,
            json={
                "path": "Inbox/hello.md",
                "content": "Body here",
                "frontmatter": {"title": "Hello"},
                "size": 42,
                "modified_at": "2026-05-02T10:00:00+00:00",
            },
        )

    bc = _bridge_with(_h)
    page = await read_page(bc, "Inbox/hello.md")
    assert page.content == "Body here"
    assert page.frontmatter == {"title": "Hello"}
    assert page.size == 42
    assert captured["path"] == "Inbox/hello.md"


@pytest.mark.asyncio
async def test_read_page_404_raises_vault_error() -> None:
    def _h(_req: httpx.Request) -> httpx.Response:
        return httpx.Response(
            404,
            json={"error": {"code": "not_found", "message": "missing"}},
        )

    bc = _bridge_with(_h)
    with pytest.raises(VaultError) as excinfo:
        await read_page(bc, "Inbox/nope.md")
    assert excinfo.value.status == 404
    assert excinfo.value.code == "not_found"


@pytest.mark.asyncio
async def test_write_page_create_returns_201_and_created_true() -> None:
    captured: dict[str, str] = {}

    def _h(req: httpx.Request) -> httpx.Response:
        body = json.loads(req.read().decode("utf-8"))
        captured["mode"] = body["mode"]
        captured["path"] = body["path"]
        return httpx.Response(
            201,
            json={
                "path": body["path"],
                "size": 10,
                "written_at": "2026-05-02T10:00:00+00:00",
            },
        )

    bc = _bridge_with(_h)
    out = await write_page(
        bc,
        path="Inbox/new.md",
        mode="create",
        content="hello",
    )
    assert out.created is True
    assert out.size == 10
    assert captured["mode"] == "create"


@pytest.mark.asyncio
async def test_write_page_replace_returns_200_and_created_false() -> None:
    def _h(_req: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "path": "Inbox/r.md",
                "size": 6,
                "written_at": "2026-05-02T10:00:00+00:00",
            },
        )

    bc = _bridge_with(_h)
    out = await write_page(
        bc,
        path="Inbox/r.md",
        mode="replace",
        content="v2",
    )
    assert out.created is False


@pytest.mark.asyncio
async def test_write_page_with_frontmatter_round_trip() -> None:
    captured: dict[str, dict[str, object]] = {}

    def _h(req: httpx.Request) -> httpx.Response:
        body = json.loads(req.read().decode("utf-8"))
        captured["body"] = body
        return httpx.Response(
            201,
            json={
                "path": body["path"],
                "size": 50,
                "written_at": "2026-05-02T10:00:00+00:00",
            },
        )

    bc = _bridge_with(_h)
    await write_page(
        bc,
        path="Inbox/x.md",
        mode="create",
        content="hi",
        frontmatter={"created": "2026-05-02", "topic": "x"},
    )
    sent_body = captured["body"]
    assert sent_body["frontmatter"] == {"created": "2026-05-02", "topic": "x"}


@pytest.mark.asyncio
async def test_append_to_inbox_uses_dated_path() -> None:
    from datetime import UTC, datetime

    captured: dict[str, str] = {}

    def _h(req: httpx.Request) -> httpx.Response:
        body = json.loads(req.read().decode("utf-8"))
        captured["path"] = body["path"]
        captured["mode"] = body["mode"]
        return httpx.Response(
            200,
            json={
                "path": body["path"],
                "size": 5,
                "written_at": "2026-05-02T10:00:00+00:00",
            },
        )

    bc = _bridge_with(_h)
    fixed_today = datetime(2026, 5, 2, 14, 0, 0, tzinfo=UTC)
    await append_to_inbox(bc, body="note line", today=fixed_today)
    assert captured["path"] == "Inbox/2026-05-02.md"
    assert captured["mode"] == "append"
