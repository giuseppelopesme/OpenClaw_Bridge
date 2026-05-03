"""Reminders provider — list/create/update/delete via osascript.

Mirrors the calendar provider's structure (TSV-ish output with `\\u001f` /
`\\u001e` separators, runner injection, escaping rules). Reminders are
scoped per *list* (the AppleScript term — "list" is the user-facing folder
e.g. "Reminders", "Groceries").

Property mapping:

| Reminder dataclass | AppleScript Reminders.app |
|--------------------|---------------------------|
| id                 | id                        |
| title              | name                      |
| list               | (name of) container/list  |
| completed          | completed                 |
| due_date           | due date (date or missing)|
| notes              | body                      |

Due dates round-trip through the same naive-ISO format the calendar
provider uses (`YYYY-MM-DDTHH:MM:SS`). The empty string means "no due
date" on the wire.
"""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass

from bridge.errors import NotFound
from bridge.providers.apple.calendar import (
    _ISO_HELPER,
    _escape,
    _format_dt,
    _parse_tsv,
)
from bridge.providers.apple.runner import run_osascript

logger = logging.getLogger("bridge.providers.apple.reminders")

Runner = Callable[[str], Awaitable[str]]


@dataclass(frozen=True)
class Reminder:
    id: str
    title: str
    list: str
    completed: bool
    due_date: str | None
    notes: str | None


class RemindersProvider:
    """Stateless wrapper around `osascript` for Reminders.app."""

    def __init__(self, runner: Runner | None = None) -> None:
        self._run: Runner = runner or run_osascript

    async def list_reminders(
        self,
        list_name: str | None = None,
        *,
        completed: bool = False,
    ) -> list[Reminder]:
        if list_name is None:
            lists_expr = "every list"
        else:
            lists_expr = f'(lists whose name is "{_escape(list_name)}")'
        completed_clause = "true" if completed else "false"
        script = (
            _ISO_HELPER
            + "set fs to (character id 31)\n"
            + "set rs to (character id 30)\n"
            + 'set out to ""\n'
            + 'tell application "Reminders"\n'
            + f"  set theLists to {lists_expr}\n"
            + "  repeat with lst in theLists\n"
            + "    repeat with r in (reminders of lst whose completed is "
            + f"{completed_clause})\n"
            + "      try\n"
            + "        set dd to isoStr(due date of r)\n"
            + "      on error\n"
            + '        set dd to ""\n'
            + "      end try\n"
            + "      try\n"
            + "        set bd to (body of r) as string\n"
            + "      on error\n"
            + '        set bd to ""\n'
            + "      end try\n"
            + "      set out to out & (id of r) & fs & (name of r) "
            + "& fs & (name of lst) & fs & ((completed of r) as string) "
            + "& fs & dd & fs & bd & rs\n"
            + "    end repeat\n"
            + "  end repeat\n"
            + "end tell\n"
            + "return out\n"
        )
        raw = await self._run(script)
        out: list[Reminder] = []
        for fields in _parse_tsv(raw):
            if len(fields) != 6:
                logger.warning(
                    "reminders_list_unparseable",
                    extra={"field_count": len(fields)},
                )
                continue
            rid, name, lst, comp, due, body = fields
            out.append(
                Reminder(
                    id=rid,
                    title=name,
                    list=lst,
                    completed=(comp.lower() == "true"),
                    due_date=due or None,
                    notes=body or None,
                ),
            )
        return out

    async def create_reminder(
        self,
        list_name: str,
        title: str,
        *,
        due_date: str | None = None,
        notes: str | None = None,
    ) -> str:
        list_e = _escape(list_name)
        title_e = _escape(title)
        props = [f'name:"{title_e}"']
        if notes is not None:
            props.append(f'body:"{_escape(notes)}"')
        if due_date is not None:
            dd = _format_dt(due_date)
            props.append(f'due date:(date "{dd}")')
        props_block = "{" + ", ".join(props) + "}"
        script = (
            'tell application "Reminders"\n'
            f'  set targetList to first list whose name is "{list_e}"\n'
            "  set newR to make new reminder at end of reminders of targetList "
            f"with properties {props_block}\n"
            "  return id of newR\n"
            "end tell\n"
        )
        return await self._run(script)

    async def update_reminder(
        self,
        reminder_id: str,
        *,
        title: str | None = None,
        notes: str | None = None,
        due_date: str | None = None,
        completed: bool | None = None,
    ) -> None:
        rid = _escape(reminder_id)
        setters: list[str] = []
        if title is not None:
            setters.append(f'set name of r to "{_escape(title)}"')
        if notes is not None:
            setters.append(f'set body of r to "{_escape(notes)}"')
        if due_date is not None:
            dd = _format_dt(due_date)
            setters.append(f'set due date of r to (date "{dd}")')
        if completed is not None:
            setters.append(f"set completed of r to {str(completed).lower()}")
        if not setters:
            return
        body = "\n      ".join(setters)
        script = (
            'tell application "Reminders"\n'
            "  repeat with lst in lists\n"
            "    try\n"
            f'      set r to (first reminder of lst whose id is "{rid}")\n'
            f"      {body}\n"
            '      return "ok"\n'
            "    end try\n"
            "  end repeat\n"
            "end tell\n"
            'return "not_found"\n'
        )
        result = await self._run(script)
        if result != "ok":
            raise NotFound(
                f"Reminder not found: {reminder_id}",
                details={"id": reminder_id},
            )

    async def delete_reminder(self, reminder_id: str) -> None:
        rid = _escape(reminder_id)
        script = (
            'tell application "Reminders"\n'
            "  repeat with lst in lists\n"
            "    try\n"
            f'      set r to (first reminder of lst whose id is "{rid}")\n'
            "      delete r\n"
            '      return "ok"\n'
            "    end try\n"
            "  end repeat\n"
            "end tell\n"
            'return "not_found"\n'
        )
        result = await self._run(script)
        if result != "ok":
            raise NotFound(
                f"Reminder not found: {reminder_id}",
                details={"id": reminder_id},
            )
