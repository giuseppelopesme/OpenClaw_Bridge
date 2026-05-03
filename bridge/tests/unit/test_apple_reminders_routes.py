"""Reminders HTTP endpoints — scope enforcement + provider wiring."""

from __future__ import annotations

from collections.abc import Awaitable, Callable

from _support import TokenFixture
from bridge.providers.apple.reminders import RemindersProvider
from fastapi.testclient import TestClient

AUTH_OK = {"Authorization": "Bearer dev-token-apple"}


def _swap_runner(client: TestClient, runner: Callable[[str], Awaitable[str]]) -> None:
    client.app.state.reminders_provider = RemindersProvider(runner=runner)


def _fixed(text: str) -> Callable[[str], Awaitable[str]]:
    async def _r(_script: str) -> str:
        return text

    return _r


def test_list_reminders_happy_path(
    client: TestClient,
    tokens: list[TokenFixture],  # noqa: ARG001
) -> None:
    fs, rs = "\x1f", "\x1e"
    raw = fs.join(["REM-1", "Buy", "Personal", "false", "", ""]) + rs
    _swap_runner(client, _fixed(raw))
    resp = client.get("/v1/reminders", headers=AUTH_OK)
    assert resp.status_code == 200
    body = resp.json()
    assert len(body["reminders"]) == 1
    assert body["reminders"][0]["title"] == "Buy"
    assert body["reminders"][0]["completed"] is False


def test_list_reminders_requires_read_scope(client: TestClient) -> None:
    resp = client.get(
        "/v1/reminders",
        headers={"Authorization": "Bearer dev-token-empty"},
    )
    assert resp.status_code == 403


def test_create_reminder_returns_201(
    client: TestClient,
    tokens: list[TokenFixture],  # noqa: ARG001
) -> None:
    _swap_runner(client, _fixed("REM-NEW"))
    resp = client.post(
        "/v1/reminders",
        json={"list": "Personal", "title": "Call mom"},
        headers=AUTH_OK,
    )
    assert resp.status_code == 201
    assert resp.json()["id"] == "REM-NEW"


def test_create_reminder_requires_write_scope(client: TestClient) -> None:
    resp = client.post(
        "/v1/reminders",
        json={"list": "Personal", "title": "x"},
        headers={"Authorization": "Bearer dev-token-empty"},
    )
    assert resp.status_code == 403


def test_update_reminder_happy_path(
    client: TestClient,
    tokens: list[TokenFixture],  # noqa: ARG001
) -> None:
    _swap_runner(client, _fixed("ok"))
    resp = client.patch(
        "/v1/reminders/REM-1",
        json={"completed": True},
        headers=AUTH_OK,
    )
    assert resp.status_code == 200
    assert resp.json()["status"] == "updated"


def test_update_reminder_missing_returns_404(
    client: TestClient,
    tokens: list[TokenFixture],  # noqa: ARG001
) -> None:
    _swap_runner(client, _fixed("not_found"))
    resp = client.patch(
        "/v1/reminders/MISSING",
        json={"title": "x"},
        headers=AUTH_OK,
    )
    assert resp.status_code == 404


def test_delete_reminder_happy_path(
    client: TestClient,
    tokens: list[TokenFixture],  # noqa: ARG001
) -> None:
    _swap_runner(client, _fixed("ok"))
    resp = client.delete("/v1/reminders/REM-1", headers=AUTH_OK)
    assert resp.status_code == 200


def test_delete_reminder_missing_returns_404(
    client: TestClient,
    tokens: list[TokenFixture],  # noqa: ARG001
) -> None:
    _swap_runner(client, _fixed("not_found"))
    resp = client.delete("/v1/reminders/MISSING", headers=AUTH_OK)
    assert resp.status_code == 404
