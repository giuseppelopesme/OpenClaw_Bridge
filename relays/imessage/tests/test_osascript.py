"""osascript send helper — escaping rules and error mapping.

Every test patches ``subprocess.run`` so we never spawn a real
osascript. The opt-in ``macos_apple`` integration test is in the bridge
repo (Session 5); this module is hermetic.
"""

from __future__ import annotations

import subprocess
from typing import Any
from unittest.mock import patch

import pytest
from relay import osascript as os_module
from relay.osascript import OsascriptError, _escape, send_imessage


class _ProcLike:
    def __init__(self, *, returncode: int = 0, stderr: bytes = b"") -> None:
        self.returncode = returncode
        self.stderr = stderr
        self.stdout = b""


def _patch_run(result: _ProcLike | Exception) -> Any:
    def _fake(*_a: object, **_kw: object) -> _ProcLike:
        if isinstance(result, Exception):
            raise result
        return result

    return patch.object(os_module.subprocess, "run", side_effect=_fake)


def test_send_happy_path_invokes_osascript() -> None:
    captured: dict[str, Any] = {}

    def _fake_run(args: list[str], **kwargs: Any) -> _ProcLike:
        captured["args"] = args
        captured["kwargs"] = kwargs
        return _ProcLike()

    with patch.object(os_module.subprocess, "run", side_effect=_fake_run):
        send_imessage(to="+39 333 1234567", body="hi")
    assert captured["args"][0] == "osascript"
    assert captured["args"][1] == "-e"
    script = captured["args"][2]
    assert '"+39 333 1234567"' in script
    assert '"hi"' in script
    assert "service type = iMessage" in script


def test_send_supports_sms_service() -> None:
    captured: dict[str, Any] = {}

    def _fake_run(args: list[str], **_kw: Any) -> _ProcLike:
        captured["script"] = args[2]
        return _ProcLike()

    with patch.object(os_module.subprocess, "run", side_effect=_fake_run):
        send_imessage(to="+39", body="x", service="SMS")
    assert "service type = SMS" in captured["script"]


def test_send_rejects_unknown_service() -> None:
    with pytest.raises(OsascriptError) as excinfo:
        send_imessage(to="+39", body="x", service="WhatsApp")
    assert excinfo.value.code == "bad_input"


def test_send_rejects_newline_in_body() -> None:
    with pytest.raises(OsascriptError) as excinfo:
        send_imessage(to="+39", body="line one\nline two")
    assert excinfo.value.code == "bad_input"


def test_send_rejects_null_byte_in_to() -> None:
    with pytest.raises(OsascriptError) as excinfo:
        send_imessage(to="+39\x00666", body="x")
    assert excinfo.value.code == "bad_input"


def test_escape_doubles_quotes_and_backslashes() -> None:
    assert _escape('say "hi" \\ end') == 'say \\"hi\\" \\\\ end'


def test_send_missing_binary_maps_to_missing_binary() -> None:
    with (
        _patch_run(FileNotFoundError("no osascript here")),
        pytest.raises(OsascriptError) as excinfo,
    ):
        send_imessage(to="+39", body="x")
    assert excinfo.value.code == "missing_binary"


def test_send_timeout_maps_to_timeout() -> None:
    timeout_exc = subprocess.TimeoutExpired(cmd="osascript", timeout=1.0)
    with _patch_run(timeout_exc), pytest.raises(OsascriptError) as excinfo:
        send_imessage(to="+39", body="x", timeout_s=1.0)
    assert excinfo.value.code == "timeout"


def test_send_non_zero_exit_includes_stderr_snippet() -> None:
    proc = _ProcLike(returncode=2, stderr=b"can't find buddy")
    with _patch_run(proc), pytest.raises(OsascriptError) as excinfo:
        send_imessage(to="+39", body="x")
    assert excinfo.value.code == "non_zero_exit"
    assert "can't find buddy" in excinfo.value.stderr


def test_send_truncates_long_stderr() -> None:
    proc = _ProcLike(returncode=1, stderr=b"x" * 2000)
    with _patch_run(proc), pytest.raises(OsascriptError) as excinfo:
        send_imessage(to="+39", body="x")
    assert len(excinfo.value.stderr) == 500
