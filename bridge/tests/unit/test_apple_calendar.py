"""CalendarProvider — happy paths and error paths against a mocked runner."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from pathlib import Path

import pytest
from bridge.errors import BadRequest, DependencyUnavailable, NotFound
from bridge.providers.apple.calendar import CalendarProvider, _escape, _format_dt

FIXTURES = Path(__file__).parent.parent / "fixtures" / "apple" / "calendar"


def _runner_returning(text: str) -> Callable[[str], Awaitable[str]]:
    async def _r(_script: str) -> str:
        return text

    return _r


def _runner_raising(exc: BaseException) -> Callable[[str], Awaitable[str]]:
    async def _r(_script: str) -> str:
        raise exc

    return _r


@pytest.mark.asyncio
async def test_list_events_parses_two_events() -> None:
    raw = (FIXTURES / "list_two_events.tsv").read_text(encoding="utf-8")
    cap: dict[str, str] = {}

    async def _r(script: str) -> str:
        cap["script"] = script
        return raw

    p = CalendarProvider(runner=_r)
    events = await p.list_events(
        "2026-05-01T00:00:00",
        "2026-05-31T23:59:59",
    )
    assert len(events) == 2
    assert events[0].id == "EVT-1-UID"
    assert events[0].title == "Lunch with team"
    assert events[0].start == "2026-05-02T12:00:00"
    assert events[0].calendar == "Personal"
    assert events[0].location == "Some Cafe"
    assert events[0].notes == "bring laptop"
    assert events[1].id == "EVT-2-UID"
    assert events[1].location is None
    assert events[1].notes is None
    # Script should embed the reformatted dates.
    assert "2026-05-01 00:00:00" in cap["script"]
    assert "2026-05-31 23:59:59" in cap["script"]
    assert "every calendar" in cap["script"]


@pytest.mark.asyncio
async def test_list_events_empty_returns_empty_list() -> None:
    p = CalendarProvider(runner=_runner_returning(""))
    events = await p.list_events("2026-05-01T00:00:00", "2026-05-31T23:59:59")
    assert events == []


@pytest.mark.asyncio
async def test_list_events_filters_by_calendar_name() -> None:
    cap: dict[str, str] = {}

    async def _r(script: str) -> str:
        cap["script"] = script
        return ""

    p = CalendarProvider(runner=_r)
    await p.list_events("2026-05-01T00:00:00", "2026-05-02T00:00:00", calendar="Glysk")
    assert '"Glysk"' in cap["script"]
    assert "every calendar" not in cap["script"]


@pytest.mark.asyncio
async def test_list_events_invalid_iso_raises_bad_request() -> None:
    p = CalendarProvider(runner=_runner_returning(""))
    with pytest.raises(BadRequest):
        await p.list_events("not-a-date", "2026-05-31T23:59:59")


@pytest.mark.asyncio
async def test_list_events_runner_failure_propagates() -> None:
    exc = DependencyUnavailable("apple bridge timeout", details={"timeout": True})
    p = CalendarProvider(runner=_runner_raising(exc))
    with pytest.raises(DependencyUnavailable):
        await p.list_events("2026-05-01T00:00:00", "2026-05-31T23:59:59")


@pytest.mark.asyncio
async def test_create_event_returns_id() -> None:
    raw = (FIXTURES / "create_returns_id.txt").read_text(encoding="utf-8")
    cap: dict[str, str] = {}

    async def _r(script: str) -> str:
        cap["script"] = script
        return raw

    p = CalendarProvider(runner=_r)
    new_id = await p.create_event(
        calendar="Personal",
        title="Standup",
        start="2026-05-02T09:00:00",
        end="2026-05-02T09:30:00",
        location=None,
        notes=None,
    )
    assert new_id == "NEW-EVT-UID-12345"
    assert '"Personal"' in cap["script"]
    assert '"Standup"' in cap["script"]
    # Optional location/notes omitted when None.
    assert "location:" not in cap["script"]
    assert "description:" not in cap["script"]


@pytest.mark.asyncio
async def test_create_event_includes_optional_fields() -> None:
    cap: dict[str, str] = {}

    async def _r(script: str) -> str:
        cap["script"] = script
        return "uid"

    p = CalendarProvider(runner=_r)
    await p.create_event(
        calendar="Personal",
        title="Demo",
        start="2026-05-02T09:00:00",
        end="2026-05-02T10:00:00",
        location="HQ",
        notes="Bring slides",
    )
    assert 'location:"HQ"' in cap["script"]
    assert 'description:"Bring slides"' in cap["script"]


@pytest.mark.asyncio
async def test_update_event_no_op_skips_runner() -> None:
    called = False

    async def _r(_script: str) -> str:
        nonlocal called
        called = True
        return "ok"

    p = CalendarProvider(runner=_r)
    await p.update_event("EVT-1-UID")
    assert called is False


@pytest.mark.asyncio
async def test_update_event_happy_path() -> None:
    cap: dict[str, str] = {}

    async def _r(script: str) -> str:
        cap["script"] = script
        return "ok"

    p = CalendarProvider(runner=_r)
    await p.update_event("EVT-1-UID", title="New title", location="HQ")
    assert '"EVT-1-UID"' in cap["script"]
    assert 'set summary of evt to "New title"' in cap["script"]
    assert 'set location of evt to "HQ"' in cap["script"]


@pytest.mark.asyncio
async def test_update_event_missing_raises_not_found() -> None:
    p = CalendarProvider(runner=_runner_returning("not_found"))
    with pytest.raises(NotFound):
        await p.update_event("MISSING", title="x")


@pytest.mark.asyncio
async def test_delete_event_happy_path() -> None:
    p = CalendarProvider(runner=_runner_returning("ok"))
    await p.delete_event("EVT-1-UID")  # no exception


@pytest.mark.asyncio
async def test_delete_event_missing_raises_not_found() -> None:
    p = CalendarProvider(runner=_runner_returning("not_found"))
    with pytest.raises(NotFound):
        await p.delete_event("MISSING")


def test_escape_rejects_newlines() -> None:
    with pytest.raises(BadRequest):
        _escape("hello\nworld")


def test_escape_rejects_null_bytes() -> None:
    with pytest.raises(BadRequest):
        _escape("hello\x00world")


def test_escape_handles_quotes_and_backslashes() -> None:
    out = _escape('he said "hi" \\ end')
    assert out == 'he said \\"hi\\" \\\\ end'


def test_format_dt_normalises_to_applescript_form() -> None:
    assert _format_dt("2026-05-02T12:00:00") == "2026-05-02 12:00:00"


def test_format_dt_rejects_garbage() -> None:
    with pytest.raises(BadRequest):
        _format_dt("not a date at all")
