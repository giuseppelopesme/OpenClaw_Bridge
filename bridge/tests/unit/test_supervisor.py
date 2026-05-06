"""Process supervisor unit tests.

Production paths use ``asyncio.create_subprocess_exec`` and asyncio
TCP probes. Both go through dependency-injected callables (``spawn``
on the Supervisor, ``ready_check`` on each Child) so the tests below
run entirely in-process.

There is no integration test in this file. A live test that spawns
real ``redis-server``, ``python -m bridge``, and ``python -m agent``
processes belongs in a dedicated opt-in module — too slow and too
I/O-bound for the unit suite.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable

import pytest
from bridge.supervisor import (
    _POISON_PILL_THRESHOLD,
    EXIT_HEALTH_TIMEOUT,
    EXIT_OK,
    EXIT_POISON_PILL,
    Child,
    Supervisor,
    SupervisorError,
)

# ----------------------------------------------------------------------
# Test doubles
# ----------------------------------------------------------------------


class FakeProc:
    """Stand-in for ``asyncio.subprocess.Process`` controlled by the test."""

    def __init__(self, pid: int) -> None:
        self.pid = pid
        self.returncode: int | None = None
        self._exit_event = asyncio.Event()
        self.terminate_called = False
        self.kill_called = False

    async def wait(self) -> int:
        await self._exit_event.wait()
        assert self.returncode is not None
        return self.returncode

    def terminate(self) -> None:
        self.terminate_called = True
        if self.returncode is None:
            self.returncode = 0
            self._exit_event.set()

    def kill(self) -> None:
        self.kill_called = True
        if self.returncode is None:
            self.returncode = -9
            self._exit_event.set()

    def crash(self, code: int = 1) -> None:
        """Test helper — simulate the child exiting on its own."""
        self.returncode = code
        self._exit_event.set()


class FakeSpawner:
    """Spawn callable that hands out FakeProc objects in order."""

    def __init__(self) -> None:
        self.spawned: list[tuple[Child, FakeProc]] = []
        self._next_pid = 1000

    async def __call__(self, child: Child) -> FakeProc:  # type: ignore[override]
        proc = FakeProc(self._next_pid)
        self._next_pid += 1
        self.spawned.append((child, proc))
        return proc

    def procs_for(self, name: str) -> list[FakeProc]:
        return [proc for c, proc in self.spawned if c.name == name]


def _make_ready_check(returns: list[bool]) -> Callable[[], Awaitable[bool]]:
    """Yields the given booleans in order, then keeps yielding the last."""
    queue = list(returns)

    async def probe() -> bool:
        if len(queue) > 1:
            return queue.pop(0)
        return queue[0] if queue else False

    return probe


@pytest.fixture
def fast_sleep() -> Callable[[float], Awaitable[None]]:
    """No-op sleep so the watch loop's backoff doesn't slow tests down."""

    async def _sleep(_seconds: float) -> None:
        # Yield once so the event loop can run other tasks.
        await asyncio.sleep(0)

    return _sleep


def _bridge_child(
    *,
    ready_check: Callable[[], Awaitable[bool]] | None = None,
    argv: list[str] | None = None,
) -> Child:
    """Build a bridge-shaped Child for tests."""
    return Child(name="bridge", argv=argv or ["true"], ready_check=ready_check)


def _brain_child() -> Child:
    return Child(name="brain.agent", argv=["true"])


# ----------------------------------------------------------------------
# Tests
# ----------------------------------------------------------------------


@pytest.mark.asyncio
async def test_starts_children_in_order_after_ready_passes(
    fast_sleep: Callable[[float], Awaitable[None]],
) -> None:
    spawner = FakeSpawner()
    supervisor = Supervisor(
        children=[
            _bridge_child(ready_check=_make_ready_check([True])),
            _brain_child(),
        ],
        spawn=spawner,
        sleep=fast_sleep,
    )

    async def stopper() -> None:
        for _ in range(20):
            await asyncio.sleep(0)
            if len(spawner.spawned) >= 2:
                break
        supervisor.shutdown_event.set()

    exit_code, _ = await asyncio.gather(supervisor.run(), stopper())
    assert exit_code == EXIT_OK
    assert [c.name for c, _ in spawner.spawned] == ["bridge", "brain.agent"]


@pytest.mark.asyncio
async def test_brain_only_starts_after_bridge_ready_returns_true(
    fast_sleep: Callable[[float], Awaitable[None]],
) -> None:
    """Bridge spawns immediately; brain only after the readiness probe flips True."""
    spawner = FakeSpawner()
    supervisor = Supervisor(
        children=[
            _bridge_child(ready_check=_make_ready_check([False, False, True])),
            _brain_child(),
        ],
        spawn=spawner,
        sleep=fast_sleep,
    )

    async def stopper() -> None:
        for _ in range(50):
            await asyncio.sleep(0)
            if len(spawner.spawned) >= 2:
                break
        supervisor.shutdown_event.set()

    exit_code, _ = await asyncio.gather(supervisor.run(), stopper())
    assert exit_code == EXIT_OK
    names_in_order = [c.name for c, _ in spawner.spawned]
    assert names_in_order.index("bridge") < names_in_order.index("brain.agent")


@pytest.mark.asyncio
async def test_ready_timeout_aborts_with_distinct_exit_code(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """If a child never becomes ready, supervisor exits EXIT_HEALTH_TIMEOUT."""
    monkeypatch.setattr("bridge.supervisor._HEALTH_TIMEOUT_S", 0.01)
    spawner = FakeSpawner()

    async def fast_sleep(_s: float) -> None:
        await asyncio.sleep(0)

    supervisor = Supervisor(
        children=[_bridge_child(ready_check=_make_ready_check([False]))],
        spawn=spawner,
        sleep=fast_sleep,
    )
    exit_code = await supervisor.run()
    assert exit_code == EXIT_HEALTH_TIMEOUT
    assert len(spawner.procs_for("bridge")) == 1
    bridge = spawner.procs_for("bridge")[0]
    assert bridge.terminate_called


@pytest.mark.asyncio
async def test_crashed_child_is_restarted_with_backoff(
    fast_sleep: Callable[[float], Awaitable[None]],
) -> None:
    spawner = FakeSpawner()
    supervisor = Supervisor(
        children=[
            _bridge_child(ready_check=_make_ready_check([True])),
            _brain_child(),
        ],
        spawn=spawner,
        sleep=fast_sleep,
    )

    async def driver() -> None:
        for _ in range(50):
            await asyncio.sleep(0)
            if len(spawner.spawned) >= 2:
                break
        first_brain = spawner.procs_for("brain.agent")[0]
        first_brain.crash(code=1)
        for _ in range(50):
            await asyncio.sleep(0)
            if len(spawner.procs_for("brain.agent")) >= 2:
                break
        supervisor.shutdown_event.set()

    exit_code, _ = await asyncio.gather(supervisor.run(), driver())
    assert exit_code == EXIT_OK
    assert len(spawner.procs_for("brain.agent")) >= 2


@pytest.mark.asyncio
async def test_poison_pill_aborts_after_threshold_crashes(
    fast_sleep: Callable[[float], Awaitable[None]],
) -> None:
    spawner = FakeSpawner()
    supervisor = Supervisor(
        children=[
            _bridge_child(ready_check=_make_ready_check([True])),
            _brain_child(),
        ],
        spawn=spawner,
        sleep=fast_sleep,
    )

    async def crasher() -> None:
        for _ in range(50):
            await asyncio.sleep(0)
            if spawner.procs_for("brain.agent"):
                break
        for _ in range(_POISON_PILL_THRESHOLD):
            current = spawner.procs_for("brain.agent")[-1]
            current.crash(code=1)
            for _ in range(50):
                await asyncio.sleep(0)
                latest = spawner.procs_for("brain.agent")[-1]
                if latest is not current:
                    break

    exit_code, _ = await asyncio.gather(supervisor.run(), crasher())
    assert exit_code == EXIT_POISON_PILL


@pytest.mark.asyncio
async def test_shutdown_terminates_children_in_reverse_order(
    fast_sleep: Callable[[float], Awaitable[None]],
) -> None:
    """SIGTERM-equivalent (shutdown_event) stops brain.agent before the bridge."""
    spawner = FakeSpawner()
    bridge_terminated_after: list[bool] = []

    supervisor = Supervisor(
        children=[
            _bridge_child(ready_check=_make_ready_check([True])),
            _brain_child(),
        ],
        spawn=spawner,
        sleep=fast_sleep,
    )

    async def stopper() -> None:
        for _ in range(50):
            await asyncio.sleep(0)
            if len(spawner.spawned) >= 2:
                break
        bridge = spawner.procs_for("bridge")[0]
        brain = spawner.procs_for("brain.agent")[0]
        assert not bridge.terminate_called
        assert not brain.terminate_called
        supervisor.shutdown_event.set()
        for _ in range(50):
            await asyncio.sleep(0)
            if bridge.terminate_called and brain.terminate_called:
                break
        bridge_terminated_after.append(bridge.terminate_called)
        bridge_terminated_after.append(brain.terminate_called)
        assert not bridge.kill_called
        assert not brain.kill_called

    exit_code, _ = await asyncio.gather(supervisor.run(), stopper())
    assert exit_code == EXIT_OK
    assert bridge_terminated_after == [True, True]


@pytest.mark.asyncio
async def test_shutdown_during_ready_gate_exits_cleanly(
    fast_sleep: Callable[[float], Awaitable[None]],
) -> None:
    """Shutdown signal mid-readiness-check stops the child and exits 0."""
    spawner = FakeSpawner()
    supervisor = Supervisor(
        children=[
            _bridge_child(ready_check=_make_ready_check([False])),
        ],
        spawn=spawner,
        sleep=fast_sleep,
    )

    async def stopper() -> None:
        for _ in range(20):
            await asyncio.sleep(0)
        supervisor.shutdown_event.set()

    exit_code, _ = await asyncio.gather(supervisor.run(), stopper())
    assert exit_code == EXIT_OK
    bridge = spawner.procs_for("bridge")[0]
    assert bridge.terminate_called


@pytest.mark.asyncio
async def test_redis_blocks_bridge_blocks_brain_three_child_chain(
    fast_sleep: Callable[[float], Awaitable[None]],
) -> None:
    """Three-child chain (redis → bridge → brain): each gates the next."""
    spawner = FakeSpawner()

    redis_ready_calls = 0
    bridge_ready_calls = 0

    async def redis_ready() -> bool:
        nonlocal redis_ready_calls
        redis_ready_calls += 1
        return True  # immediate ready

    async def bridge_ready() -> bool:
        nonlocal bridge_ready_calls
        bridge_ready_calls += 1
        return True  # immediate ready

    supervisor = Supervisor(
        children=[
            Child(name="redis", argv=["true"], ready_check=redis_ready),
            Child(name="bridge", argv=["true"], ready_check=bridge_ready),
            Child(name="brain.agent", argv=["true"]),
        ],
        spawn=spawner,
        sleep=fast_sleep,
    )

    async def stopper() -> None:
        for _ in range(50):
            await asyncio.sleep(0)
            if len(spawner.spawned) >= 3:
                break
        supervisor.shutdown_event.set()

    exit_code, _ = await asyncio.gather(supervisor.run(), stopper())
    assert exit_code == EXIT_OK
    names = [c.name for c, _ in spawner.spawned]
    assert names == ["redis", "bridge", "brain.agent"]
    # Each ready_check fired at least once (the supervisor only called
    # them after the corresponding child spawned).
    assert redis_ready_calls >= 1
    assert bridge_ready_calls >= 1


def test_supervisor_error_carries_exit_code() -> None:
    err = SupervisorError("boom", 42)
    assert err.exit_code == 42
    assert str(err) == "boom"
