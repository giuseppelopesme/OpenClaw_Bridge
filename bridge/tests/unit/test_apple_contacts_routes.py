"""Contacts HTTP endpoint — scope enforcement + provider wiring."""

from __future__ import annotations

from collections.abc import Awaitable, Callable

from _support import TokenFixture
from bridge.providers.apple.contacts import ContactsProvider
from fastapi.testclient import TestClient

AUTH_OK = {"Authorization": "Bearer dev-token-apple"}


def _swap_runner(client: TestClient, runner: Callable[[str], Awaitable[str]]) -> None:
    client.app.state.contacts_provider = ContactsProvider(runner=runner)


def _fixed(text: str) -> Callable[[str], Awaitable[str]]:
    async def _r(_script: str) -> str:
        return text

    return _r


def test_search_happy_path(
    client: TestClient,
    tokens: list[TokenFixture],  # noqa: ARG001
) -> None:
    fs, rs = "\x1f", "\x1e"
    raw = fs.join(["Alice Smith", "+39 1234|", "alice@x.com|"]) + rs
    _swap_runner(client, _fixed(raw))
    resp = client.get("/v1/contacts/search?q=alice", headers=AUTH_OK)
    assert resp.status_code == 200
    body = resp.json()
    assert len(body["contacts"]) == 1
    assert body["contacts"][0]["name"] == "Alice Smith"
    assert body["contacts"][0]["phones"] == ["+39 1234"]
    assert body["contacts"][0]["emails"] == ["alice@x.com"]


def test_search_requires_read_scope(client: TestClient) -> None:
    resp = client.get(
        "/v1/contacts/search?q=alice",
        headers={"Authorization": "Bearer dev-token-empty"},
    )
    assert resp.status_code == 403


def test_search_missing_query_returns_422(
    client: TestClient,
    tokens: list[TokenFixture],  # noqa: ARG001
) -> None:
    _swap_runner(client, _fixed(""))
    resp = client.get("/v1/contacts/search", headers=AUTH_OK)
    assert resp.status_code == 422
