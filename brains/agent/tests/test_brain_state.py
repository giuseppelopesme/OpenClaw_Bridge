"""Brain state — dedup round-trip (drafts live in the bridge now)."""

from __future__ import annotations

from pathlib import Path

import pytest
from agent.state import State


@pytest.fixture
async def state(tmp_path: Path):
    s = State(tmp_path / "agent.state.db")
    await s.open()
    try:
        yield s
    finally:
        await s.close()


@pytest.mark.asyncio
async def test_is_processed_false_initially(state: State) -> None:
    assert await state.is_processed("evt-1") is False


@pytest.mark.asyncio
async def test_mark_processed_round_trip(state: State) -> None:
    await state.mark_processed("evt-1", "imessage.received.agent")
    assert await state.is_processed("evt-1") is True


@pytest.mark.asyncio
async def test_mark_processed_double_call_is_no_op(state: State) -> None:
    await state.mark_processed("evt-1", "imessage.received.agent")
    # Second call must not raise (UNIQUE conflict is swallowed).
    await state.mark_processed("evt-1", "imessage.received.agent")
    assert await state.is_processed("evt-1") is True


@pytest.mark.asyncio
async def test_state_persists_across_reopens(tmp_path: Path) -> None:
    db = tmp_path / "persist.db"
    s = State(db)
    await s.open()
    await s.mark_processed("evt-persist", "imessage.received.agent")
    await s.close()

    s2 = State(db)
    await s2.open()
    try:
        assert await s2.is_processed("evt-persist") is True
    finally:
        await s2.close()
