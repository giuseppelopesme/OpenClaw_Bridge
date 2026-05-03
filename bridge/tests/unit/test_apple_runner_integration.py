"""Real-osascript integration test (opt-in via the `macos_apple` marker).

Run with:

    uv run --no-sync pytest -m macos_apple

Skipped by default. The first time osascript talks to System Events, macOS
may prompt for Automation permissions; grant once.
"""

from __future__ import annotations

import pytest
from bridge.providers.apple.runner import run_osascript


@pytest.mark.macos_apple
@pytest.mark.asyncio
async def test_run_osascript_returns_true_against_system_events() -> None:
    out = await run_osascript(
        'tell application "System Events" to return true',
        timeout_s=5.0,
    )
    assert out == "true"
