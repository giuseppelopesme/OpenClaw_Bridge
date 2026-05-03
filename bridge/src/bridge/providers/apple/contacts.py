"""Contacts provider — read-only search via osascript.

The bridge talks to Contacts.app to find people by name. v1 is read-only:
no create/update/delete. Output uses the same TSV-ish framing the calendar
and reminders providers use, plus an inner pipe (`|`) inside the phones
and emails fields to join multiple values per person.

Schema (per `docs/api-contract.md`):

    { name: str, phones: list[str], emails: list[str] }
"""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass

from bridge.providers.apple.calendar import _escape, _parse_tsv
from bridge.providers.apple.runner import run_osascript

logger = logging.getLogger("bridge.providers.apple.contacts")

Runner = Callable[[str], Awaitable[str]]

# Inner separator inside the phones / emails fields. `|` is unlikely in
# either; we still split-and-discard empties to be defensive.
_INNER: str = "|"


@dataclass(frozen=True)
class Contact:
    name: str
    phones: list[str]
    emails: list[str]


class ContactsProvider:
    """Stateless wrapper around `osascript` for Contacts.app."""

    def __init__(self, runner: Runner | None = None) -> None:
        self._run: Runner = runner or run_osascript

    async def search(self, query: str, limit: int = 10) -> list[Contact]:
        q = _escape(query)
        # AppleScript "people" returns *every* contact when matching. We
        # cap server-side because Contacts.app does not natively limit
        # within `whose` clauses; the bridge enforces the API limit.
        script = (
            "set fs to (character id 31)\n"
            "set rs to (character id 30)\n"
            'set out to ""\n'
            "set seen to 0\n"
            'tell application "Contacts"\n'
            f'  set ppl to (every person whose name contains "{q}")\n'
            "  repeat with p in ppl\n"
            f"    if seen >= {limit} then exit repeat\n"
            '    set phs to ""\n'
            "    repeat with ph in (phones of p)\n"
            f'      set phs to phs & (value of ph) & "{_INNER}"\n'
            "    end repeat\n"
            '    set ems to ""\n'
            "    repeat with em in (emails of p)\n"
            f'      set ems to ems & (value of em) & "{_INNER}"\n'
            "    end repeat\n"
            "    set out to out & ((name of p) as string) & fs & phs "
            "& fs & ems & rs\n"
            "    set seen to seen + 1\n"
            "  end repeat\n"
            "end tell\n"
            "return out\n"
        )
        raw = await self._run(script)
        contacts: list[Contact] = []
        for fields in _parse_tsv(raw):
            if len(fields) != 3:
                logger.warning(
                    "contacts_search_unparseable",
                    extra={"field_count": len(fields)},
                )
                continue
            name, phones_blob, emails_blob = fields
            phones = [s for s in phones_blob.split(_INNER) if s]
            emails = [s for s in emails_blob.split(_INNER) if s]
            contacts.append(Contact(name=name, phones=phones, emails=emails))
        return contacts
