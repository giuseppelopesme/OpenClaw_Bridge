"""ContactsProvider — search happy paths and edge cases."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from pathlib import Path

import pytest
from bridge.providers.apple.contacts import ContactsProvider

FIXTURES = Path(__file__).parent.parent / "fixtures" / "apple" / "contacts"


def _runner_returning(text: str) -> Callable[[str], Awaitable[str]]:
    async def _r(_script: str) -> str:
        return text

    return _r


@pytest.mark.asyncio
async def test_search_parses_two_contacts() -> None:
    raw = (FIXTURES / "search_two_results.tsv").read_text(encoding="utf-8")
    cap: dict[str, str] = {}

    async def _r(script: str) -> str:
        cap["script"] = script
        return raw

    p = ContactsProvider(runner=_r)
    contacts = await p.search("smith")
    assert len(contacts) == 2
    assert contacts[0].name == "Alice Smith"
    assert contacts[0].phones == ["+39 333 1234567", "+39 02 1234567"]
    assert contacts[0].emails == ["alice@example.com"]
    assert contacts[1].phones == []
    assert contacts[1].emails == ["bob@example.com", "bob.jones@work.com"]
    assert '"smith"' in cap["script"]


@pytest.mark.asyncio
async def test_search_empty_returns_empty_list() -> None:
    p = ContactsProvider(runner=_runner_returning(""))
    assert await p.search("nobody") == []


@pytest.mark.asyncio
async def test_search_limit_injected_into_script() -> None:
    cap: dict[str, str] = {}

    async def _r(script: str) -> str:
        cap["script"] = script
        return ""

    p = ContactsProvider(runner=_r)
    await p.search("alice", limit=5)
    assert "if seen >= 5" in cap["script"]
