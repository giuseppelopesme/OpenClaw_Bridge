"""Calendar provider — list/create/update/delete events via osascript.

The bridge talks to Calendar.app through AppleScript. This module owns the
script templates, the input-escaping rules, and the output-parsing for the
TSV-like format the scripts emit (`\\u001f` field separator, `\\u001e` record
separator — chosen because they are ASCII control characters that do not
appear in calendar text).

Every method funnels through `runner.run_osascript`. Tests monkeypatch the
runner; the integration tests opt into the real binary via the
`macos_apple` pytest marker.

### AppleScript design notes

- Dates: callers pass ISO 8601 strings. We reformat to AppleScript's
  preferred `YYYY-MM-DD HH:MM:SS` form before injection. Output dates
  are rebuilt manually (no NSDateFormatter dependency) as
  `YYYY-MM-DDTHH:MM:SS` — naive ISO 8601 for v1.
- Strings: we escape backslashes and double quotes, and reject newlines or
  null bytes outright (raise BadRequest). AppleScript's string literals
  cannot contain raw newlines and would surface as parse errors otherwise.
- Calendar name: free-form. We do not validate against a known list — bad
  names surface as "calendar not found" via the runner.
- Per-script size: inline iso helper + tell block runs ~20 lines, slightly
  over the SESSION-NOTES.md "~15 lines" soft limit. Accepted as the
  one-shot approach; PyObjC/EventKit migration is the v2 call when
  performance becomes a bottleneck.
"""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import datetime

from bridge.errors import BadRequest, NotFound
from bridge.providers.apple.runner import run_osascript

logger = logging.getLogger("bridge.providers.apple.calendar")

# AppleScript uses these as our field/record separators in TSV-ish output.
FS: str = "\x1f"
RS: str = "\x1e"

Runner = Callable[[str], Awaitable[str]]


@dataclass(frozen=True)
class Event:
    id: str
    title: str
    start: str
    end: str
    calendar: str
    location: str | None
    notes: str | None


def _escape(value: str) -> str:
    """AppleScript string escaping. Reject newlines and null bytes upfront."""
    if "\n" in value or "\r" in value or "\x00" in value:
        raise BadRequest(
            "AppleScript strings cannot contain newlines or null bytes.",
            details={"value_preview": value[:50]},
        )
    return value.replace("\\", "\\\\").replace('"', '\\"')


def _format_dt(iso: str) -> str:
    """Reformat ISO 8601 → `YYYY-MM-DD HH:MM:SS` for AppleScript `date "..."`."""
    try:
        dt = datetime.fromisoformat(iso)
    except ValueError as exc:
        raise BadRequest(
            "Invalid ISO 8601 date.",
            details={"value": iso},
        ) from exc
    return dt.strftime("%Y-%m-%d %H:%M:%S")


_ISO_HELPER: str = (
    "on isoStr(d)\n"
    "  set y to year of d as integer\n"
    "  set m to month of d as integer\n"
    "  set dd to day of d as integer\n"
    "  set h to hours of d\n"
    "  set mi to minutes of d\n"
    "  set sc to (seconds of d) as integer\n"
    '  return (y as string) & "-" & text -2 thru -1 of ("0" & m) & "-" & '
    'text -2 thru -1 of ("0" & dd) & "T" & text -2 thru -1 of ("0" & h) & ":" & '
    'text -2 thru -1 of ("0" & mi) & ":" & text -2 thru -1 of ("0" & sc)\n'
    "end isoStr\n"
)


def _parse_tsv(raw: str) -> list[list[str]]:
    """Split runner output by RS into records, each split by FS into fields.

    Trailing RS produces an empty record which we drop. Empty input returns
    an empty list.
    """
    if not raw:
        return []
    out: list[list[str]] = []
    for record in raw.split(RS):
        if record == "":
            continue
        out.append(record.split(FS))
    return out


class CalendarProvider:
    """Stateless wrapper around `osascript` for Calendar.app."""

    def __init__(self, runner: Runner | None = None) -> None:
        self._run: Runner = runner or run_osascript

    async def list_events(
        self,
        from_dt: str,
        to_dt: str,
        calendar: str | None = None,
    ) -> list[Event]:
        sd = _format_dt(from_dt)
        ed = _format_dt(to_dt)
        if calendar is None:
            cals_expr = "every calendar"
        else:
            cals_expr = f'(calendars whose name is "{_escape(calendar)}")'
        script = (
            _ISO_HELPER
            + "set fs to (character id 31)\n"
            + "set rs to (character id 30)\n"
            + f'set sd to date "{sd}"\n'
            + f'set ed to date "{ed}"\n'
            + 'set out to ""\n'
            + 'tell application "Calendar"\n'
            + f"  set theCals to {cals_expr}\n"
            + "  repeat with cal in theCals\n"
            + "    repeat with evt in (every event of cal whose start date "
            + ">= sd and start date <= ed)\n"
            + "      try\n"
            + "        set loc to (location of evt) as string\n"
            + "      on error\n"
            + '        set loc to ""\n'
            + "      end try\n"
            + "      try\n"
            + "        set nts to (description of evt) as string\n"
            + "      on error\n"
            + '        set nts to ""\n'
            + "      end try\n"
            + "      set out to out & (uid of evt) & fs & (summary of evt) "
            + "& fs & isoStr(start date of evt) & fs & isoStr(end date of evt) "
            + "& fs & (name of cal) & fs & loc & fs & nts & rs\n"
            + "    end repeat\n"
            + "  end repeat\n"
            + "end tell\n"
            + "return out\n"
        )
        raw = await self._run(script)
        events: list[Event] = []
        for fields in _parse_tsv(raw):
            if len(fields) != 7:
                logger.warning(
                    "calendar_list_event_unparseable",
                    extra={"field_count": len(fields)},
                )
                continue
            uid, title, start, end, cal_name, location, notes = fields
            events.append(
                Event(
                    id=uid,
                    title=title,
                    start=start,
                    end=end,
                    calendar=cal_name,
                    location=location or None,
                    notes=notes or None,
                ),
            )
        return events

    async def create_event(
        self,
        calendar: str,
        title: str,
        start: str,
        end: str,
        location: str | None = None,
        notes: str | None = None,
    ) -> str:
        sd = _format_dt(start)
        ed = _format_dt(end)
        cal_e = _escape(calendar)
        title_e = _escape(title)
        props = [
            f'summary:"{title_e}"',
            "start date:sd",
            "end date:ed",
        ]
        if location is not None:
            props.append(f'location:"{_escape(location)}"')
        if notes is not None:
            props.append(f'description:"{_escape(notes)}"')
        props_block = "{" + ", ".join(props) + "}"
        script = (
            f'set sd to date "{sd}"\n'
            f'set ed to date "{ed}"\n'
            'tell application "Calendar"\n'
            f'  set targetCal to first calendar whose name is "{cal_e}"\n'
            f"  set newEvt to make new event at end of events of targetCal "
            f"with properties {props_block}\n"
            "  return uid of newEvt\n"
            "end tell\n"
        )
        return await self._run(script)

    async def update_event(
        self,
        event_id: str,
        *,
        title: str | None = None,
        start: str | None = None,
        end: str | None = None,
        location: str | None = None,
        notes: str | None = None,
        calendar: str | None = None,
    ) -> None:
        # PATCH semantics: only the named fields are updated. Unknown event id
        # surfaces as the runner's "not_found" sentinel → NotFound from us.
        _ = calendar  # moving an event between calendars is not supported in v1.
        eid = _escape(event_id)
        setters: list[str] = []
        if title is not None:
            setters.append(f'set summary of evt to "{_escape(title)}"')
        if start is not None:
            sd = _format_dt(start)
            setters.append(f'set start date of evt to (date "{sd}")')
        if end is not None:
            ed = _format_dt(end)
            setters.append(f'set end date of evt to (date "{ed}")')
        if location is not None:
            setters.append(f'set location of evt to "{_escape(location)}"')
        if notes is not None:
            setters.append(f'set description of evt to "{_escape(notes)}"')
        if not setters:
            return  # nothing to do
        body = "\n      ".join(setters)
        script = (
            'tell application "Calendar"\n'
            "  repeat with cal in calendars\n"
            "    try\n"
            f'      set evt to (first event of cal whose uid is "{eid}")\n'
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
                f"Calendar event not found: {event_id}",
                details={"id": event_id},
            )

    async def delete_event(self, event_id: str) -> None:
        eid = _escape(event_id)
        script = (
            'tell application "Calendar"\n'
            "  repeat with cal in calendars\n"
            "    try\n"
            f'      set evt to (first event of cal whose uid is "{eid}")\n'
            "      delete evt\n"
            '      return "ok"\n'
            "    end try\n"
            "  end repeat\n"
            "end tell\n"
            'return "not_found"\n'
        )
        result = await self._run(script)
        if result != "ok":
            raise NotFound(
                f"Calendar event not found: {event_id}",
                details={"id": event_id},
            )
