"""RemindersProvider — happy paths and error paths against a mocked runner."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from pathlib import Path

import pytest
from bridge.errors import NotFound
from bridge.providers.apple.reminders import RemindersProvider

FIXTURES = Path(__file__).parent.parent / "fixtures" / "apple" / "reminders"


def _runner_returning(text: str) -> Callable[[str], Awaitable[str]]:
    async def _r(_script: str) -> str:
        return text

    return _r


@pytest.mark.asyncio
async def test_list_reminders_parses_two() -> None:
    raw = (FIXTURES / "list_two_reminders.tsv").read_text(encoding="utf-8")
    cap: dict[str, str] = {}

    async def _r(script: str) -> str:
        cap["script"] = script
        return raw

    p = RemindersProvider(runner=_r)
    items = await p.list_reminders()
    assert len(items) == 2
    assert items[0].title == "Buy groceries"
    assert items[0].list == "Personal"
    assert items[0].completed is False
    assert items[0].due_date == "2026-05-03T18:00:00"
    assert items[0].notes == "milk, eggs"
    assert items[1].due_date is None
    assert items[1].notes is None
    assert "every list" in cap["script"]
    assert "completed is false" in cap["script"]


@pytest.mark.asyncio
async def test_list_reminders_filters_by_list_and_completed() -> None:
    cap: dict[str, str] = {}

    async def _r(script: str) -> str:
        cap["script"] = script
        return ""

    p = RemindersProvider(runner=_r)
    await p.list_reminders("Glysk", completed=True)
    assert '"Glysk"' in cap["script"]
    assert "completed is true" in cap["script"]


@pytest.mark.asyncio
async def test_list_reminders_empty_returns_empty_list() -> None:
    p = RemindersProvider(runner=_runner_returning(""))
    items = await p.list_reminders()
    assert items == []


@pytest.mark.asyncio
async def test_create_reminder_returns_id() -> None:
    raw = (FIXTURES / "create_returns_id.txt").read_text(encoding="utf-8")
    cap: dict[str, str] = {}

    async def _r(script: str) -> str:
        cap["script"] = script
        return raw

    p = RemindersProvider(runner=_r)
    new_id = await p.create_reminder("Personal", "Call dentist")
    assert new_id == "x-apple-reminderkit://REMCDReminder/NEW-REM-UID"
    assert '"Personal"' in cap["script"]
    assert '"Call dentist"' in cap["script"]
    # Optional fields omitted when None.
    assert "due date:" not in cap["script"]
    assert "body:" not in cap["script"]


@pytest.mark.asyncio
async def test_create_reminder_includes_optional_fields() -> None:
    cap: dict[str, str] = {}

    async def _r(script: str) -> str:
        cap["script"] = script
        return "uid"

    p = RemindersProvider(runner=_r)
    await p.create_reminder(
        "Personal",
        "Take meds",
        due_date="2026-05-03T08:00:00",
        notes="vitamin D",
    )
    assert "due date:(date " in cap["script"]
    assert 'body:"vitamin D"' in cap["script"]


@pytest.mark.asyncio
async def test_update_reminder_no_op_skips_runner() -> None:
    called = False

    async def _r(_script: str) -> str:
        nonlocal called
        called = True
        return "ok"

    p = RemindersProvider(runner=_r)
    await p.update_reminder("REM-1")
    assert called is False


@pytest.mark.asyncio
async def test_update_reminder_completed_true() -> None:
    cap: dict[str, str] = {}

    async def _r(script: str) -> str:
        cap["script"] = script
        return "ok"

    p = RemindersProvider(runner=_r)
    await p.update_reminder("REM-1", completed=True)
    assert "set completed of r to true" in cap["script"]


@pytest.mark.asyncio
async def test_update_reminder_missing_raises_not_found() -> None:
    p = RemindersProvider(runner=_runner_returning("not_found"))
    with pytest.raises(NotFound):
        await p.update_reminder("MISSING", title="x")


@pytest.mark.asyncio
async def test_delete_reminder_happy_path() -> None:
    p = RemindersProvider(runner=_runner_returning("ok"))
    await p.delete_reminder("REM-1")


@pytest.mark.asyncio
async def test_delete_reminder_missing_raises_not_found() -> None:
    p = RemindersProvider(runner=_runner_returning("not_found"))
    with pytest.raises(NotFound):
        await p.delete_reminder("MISSING")
