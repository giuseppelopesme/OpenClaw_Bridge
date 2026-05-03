"""Calendar HTTP endpoints — scope enforcement + provider wiring."""

from __future__ import annotations

from collections.abc import Awaitable, Callable

from _support import TokenFixture
from bridge.providers.apple.calendar import CalendarProvider
from fastapi.testclient import TestClient

AUTH_OK = {"Authorization": "Bearer dev-token-apple"}


def _swap_runner(client: TestClient, runner: Callable[[str], Awaitable[str]]) -> None:
    client.app.state.calendar_provider = CalendarProvider(runner=runner)


def _fixed(text: str) -> Callable[[str], Awaitable[str]]:
    async def _r(_script: str) -> str:
        return text

    return _r


def test_list_events_happy_path(
    client: TestClient,
    tokens: list[TokenFixture],  # noqa: ARG001
) -> None:
    fs, rs = "\x1f", "\x1e"
    raw = fs.join(
        [
            "EVT-1",
            "Lunch",
            "2026-05-02T12:00:00",
            "2026-05-02T13:00:00",
            "Personal",
            "",
            "",
        ],
    )
    _swap_runner(client, _fixed(raw + rs))
    resp = client.get(
        "/v1/calendar/events?from=2026-05-01T00:00:00&to=2026-05-31T23:59:59",
        headers=AUTH_OK,
    )
    assert resp.status_code == 200
    body = resp.json()
    assert len(body["events"]) == 1
    assert body["events"][0]["id"] == "EVT-1"
    assert body["events"][0]["title"] == "Lunch"
    assert body["events"][0]["calendar"] == "Personal"
    assert body["events"][0]["location"] is None


def test_list_events_requires_read_scope(client: TestClient) -> None:
    resp = client.get(
        "/v1/calendar/events?from=2026-05-01T00:00:00&to=2026-05-31T23:59:59",
        headers={"Authorization": "Bearer dev-token-empty"},
    )
    assert resp.status_code == 403
    assert resp.json()["error"]["code"] == "forbidden_scope"


def test_create_event_returns_201_with_id_and_url(
    client: TestClient,
    tokens: list[TokenFixture],  # noqa: ARG001
) -> None:
    _swap_runner(client, _fixed("NEW-UID"))
    resp = client.post(
        "/v1/calendar/events",
        json={
            "calendar": "Personal",
            "title": "Standup",
            "start": "2026-05-02T09:00:00",
            "end": "2026-05-02T09:30:00",
        },
        headers=AUTH_OK,
    )
    assert resp.status_code == 201
    body = resp.json()
    assert body["id"] == "NEW-UID"
    assert body["url"] == "calshow:NEW-UID"


def test_create_event_requires_write_scope(client: TestClient) -> None:
    resp = client.post(
        "/v1/calendar/events",
        json={
            "calendar": "Personal",
            "title": "x",
            "start": "2026-05-02T09:00:00",
            "end": "2026-05-02T09:30:00",
        },
        headers={"Authorization": "Bearer dev-token-empty"},
    )
    assert resp.status_code == 403


def test_create_event_bad_date_returns_400(
    client: TestClient,
    tokens: list[TokenFixture],  # noqa: ARG001
) -> None:
    _swap_runner(client, _fixed("ignored"))
    resp = client.post(
        "/v1/calendar/events",
        json={
            "calendar": "Personal",
            "title": "x",
            "start": "not-a-date",
            "end": "2026-05-02T09:30:00",
        },
        headers=AUTH_OK,
    )
    assert resp.status_code == 400
    assert resp.json()["error"]["code"] == "bad_request"


def test_update_event_happy_path(
    client: TestClient,
    tokens: list[TokenFixture],  # noqa: ARG001
) -> None:
    _swap_runner(client, _fixed("ok"))
    resp = client.patch(
        "/v1/calendar/events/EVT-1",
        json={"title": "Renamed"},
        headers=AUTH_OK,
    )
    assert resp.status_code == 200
    assert resp.json()["status"] == "updated"


def test_update_event_missing_returns_404(
    client: TestClient,
    tokens: list[TokenFixture],  # noqa: ARG001
) -> None:
    _swap_runner(client, _fixed("not_found"))
    resp = client.patch(
        "/v1/calendar/events/MISSING",
        json={"title": "Whatever"},
        headers=AUTH_OK,
    )
    assert resp.status_code == 404
    assert resp.json()["error"]["code"] == "not_found"


def test_delete_event_happy_path(
    client: TestClient,
    tokens: list[TokenFixture],  # noqa: ARG001
) -> None:
    _swap_runner(client, _fixed("ok"))
    resp = client.delete("/v1/calendar/events/EVT-1", headers=AUTH_OK)
    assert resp.status_code == 200
    assert resp.json()["status"] == "deleted"


def test_delete_event_missing_returns_404(
    client: TestClient,
    tokens: list[TokenFixture],  # noqa: ARG001
) -> None:
    _swap_runner(client, _fixed("not_found"))
    resp = client.delete("/v1/calendar/events/MISSING", headers=AUTH_OK)
    assert resp.status_code == 404
