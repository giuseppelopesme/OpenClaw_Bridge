#!/usr/bin/env python3
"""Operator-run helper: dump live osascript output as test fixtures.

Runs each Apple provider once against the real host and writes the raw
runner output to `bridge/tests/fixtures/apple/` so unit tests have realistic
canned data without re-prompting macOS for TCC permissions every run.

This is NOT run in CI. It exists so a developer on the dev box can refresh
fixtures after macOS or app updates change the AppleScript surface.

Pre-flight (one-time, per resource):
    The first invocation prompts macOS for Automation/Calendar/Reminders/
    Contacts access. Grant via System Settings → Privacy & Security →
    Automation. If a grant is forgotten, the runner returns
    `DependencyUnavailable` with the stderr in details and the bridge
    silently reports `apple_bridge: down` on /v1/health.

Usage:
    uv run --no-sync python tools/capture-osascript-fixtures.py
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

from bridge.providers.apple.calendar import CalendarProvider
from bridge.providers.apple.contacts import ContactsProvider
from bridge.providers.apple.reminders import RemindersProvider
from bridge.providers.apple.runner import run_osascript

REPO_ROOT = Path(__file__).resolve().parent.parent
FIXTURES = REPO_ROOT / "bridge" / "tests" / "fixtures" / "apple"


async def _capture_calendar() -> None:
    """Run a single list_events query for the next 30 days; dump the runner output."""
    cap: dict[str, str] = {}

    async def _capturing_runner(script: str) -> str:
        out = await run_osascript(script, timeout_s=30.0)
        cap["script"] = script
        cap["out"] = out
        return out

    p = CalendarProvider(runner=_capturing_runner)
    await p.list_events("2026-05-01T00:00:00", "2026-06-01T00:00:00")
    target = FIXTURES / "calendar" / "live_list_events.tsv"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(cap["out"], encoding="utf-8")
    sys.stdout.write(f"Wrote {target.relative_to(REPO_ROOT)} ({len(cap['out'])} bytes)\n")


async def _capture_reminders() -> None:
    cap: dict[str, str] = {}

    async def _capturing_runner(script: str) -> str:
        out = await run_osascript(script, timeout_s=30.0)
        cap["out"] = out
        return out

    p = RemindersProvider(runner=_capturing_runner)
    await p.list_reminders()
    target = FIXTURES / "reminders" / "live_list_reminders.tsv"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(cap["out"], encoding="utf-8")
    sys.stdout.write(f"Wrote {target.relative_to(REPO_ROOT)} ({len(cap['out'])} bytes)\n")


async def _capture_contacts() -> None:
    cap: dict[str, str] = {}

    async def _capturing_runner(script: str) -> str:
        out = await run_osascript(script, timeout_s=30.0)
        cap["out"] = out
        return out

    p = ContactsProvider(runner=_capturing_runner)
    # `a` is broad enough to return at least one row in most address books.
    await p.search("a", limit=5)
    target = FIXTURES / "contacts" / "live_search.tsv"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(cap["out"], encoding="utf-8")
    sys.stdout.write(f"Wrote {target.relative_to(REPO_ROOT)} ({len(cap['out'])} bytes)\n")


async def main() -> int:
    sys.stdout.write("Capturing osascript fixtures from the live host.\n")
    sys.stdout.write("If macOS prompts for Automation access, grant once per app.\n\n")
    await _capture_calendar()
    await _capture_reminders()
    await _capture_contacts()
    sys.stdout.write("\nDone.\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
