"""Apple runner — exit-code, timeout, and missing-binary mappings.

These tests exercise `run_osascript` against shell substitutes so we cover
the error-mapping branches without relying on a real osascript binary or
TCC permissions on the host.

The opt-in `macos_apple` integration test (separate file) hits the real
binary via a tiny inert script.
"""

from __future__ import annotations

import asyncio

import pytest
from bridge.errors import DependencyUnavailable
from bridge.providers.apple import runner as runner_mod


class _FakeProc:
    """Stand-in for asyncio.subprocess.Process — implements only what we use."""

    def __init__(
        self,
        *,
        stdout: bytes = b"",
        stderr: bytes = b"",
        returncode: int = 0,
        delay: float = 0.0,
    ) -> None:
        self._stdout = stdout
        self._stderr = stderr
        self.returncode = returncode
        self._delay = delay
        self._killed = False

    async def communicate(self) -> tuple[bytes, bytes]:
        if self._delay:
            await asyncio.sleep(self._delay)
        return self._stdout, self._stderr

    async def wait(self) -> int:
        return self.returncode

    def kill(self) -> None:
        self._killed = True


def _install_fake(
    monkeypatch: pytest.MonkeyPatch,
    proc_or_exc: _FakeProc | Exception,
) -> None:
    async def fake(*_args: object, **_kwargs: object) -> _FakeProc:
        if isinstance(proc_or_exc, Exception):
            raise proc_or_exc
        return proc_or_exc

    monkeypatch.setattr(runner_mod.asyncio, "create_subprocess_exec", fake)


@pytest.mark.asyncio
async def test_run_osascript_returns_stripped_stdout(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_fake(monkeypatch, _FakeProc(stdout=b"hello world\n"))
    out = await runner_mod.run_osascript("anything")
    assert out == "hello world"


@pytest.mark.asyncio
async def test_run_osascript_non_zero_exit_raises_dependency_unavailable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_fake(monkeypatch, _FakeProc(returncode=1, stderr=b"some error message"))
    with pytest.raises(DependencyUnavailable) as excinfo:
        await runner_mod.run_osascript("anything")
    assert excinfo.value.details["exit_code"] == 1
    assert "some error message" in excinfo.value.details["stderr"]


@pytest.mark.asyncio
async def test_run_osascript_timeout_raises_dependency_unavailable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_fake(monkeypatch, _FakeProc(delay=10.0))
    with pytest.raises(DependencyUnavailable) as excinfo:
        await runner_mod.run_osascript("anything", timeout_s=0.05)
    assert excinfo.value.details["timeout"] is True


@pytest.mark.asyncio
async def test_run_osascript_missing_binary_raises_dependency_unavailable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_fake(monkeypatch, FileNotFoundError("nope"))
    with pytest.raises(DependencyUnavailable) as excinfo:
        await runner_mod.run_osascript("anything")
    assert excinfo.value.details["missing"] == "osascript"


@pytest.mark.asyncio
async def test_run_osascript_truncates_long_stderr(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    blob = b"x" * 2000
    _install_fake(monkeypatch, _FakeProc(returncode=2, stderr=blob))
    with pytest.raises(DependencyUnavailable) as excinfo:
        await runner_mod.run_osascript("anything")
    # Cap is 500 chars; the snippet should be exactly that.
    assert len(excinfo.value.details["stderr"]) == 500
