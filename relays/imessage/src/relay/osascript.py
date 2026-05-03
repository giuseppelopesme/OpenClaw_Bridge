"""Send a single iMessage via Messages.app over osascript.

The relay is sync. A blocking ``subprocess.run`` is the right primitive
— each send takes a small fraction of a second, the dispatch loop is
serial per-agent, and async machinery would buy us nothing for ~200 LOC
of relay code.

Input escaping rules mirror the bridge's calendar provider: reject any
input containing newline, carriage return, or null byte (those would
break the AppleScript string literal); double backslashes and double
quotes. Failures (binary missing, non-zero exit, timeout) are surfaced
as ``OsascriptError`` so the dispatch loop can emit the
``imessage.send.failed.{agent}`` outcome with the stderr snippet.
"""

from __future__ import annotations

import logging
import subprocess
from typing import Final

logger = logging.getLogger("relay.osascript")

OSASCRIPT_BIN: Final[str] = "osascript"
DEFAULT_TIMEOUT_S: Final[float] = 30.0
_STDERR_SNIPPET_LIMIT: Final[int] = 500


class OsascriptError(Exception):
    """Raised when ``osascript`` does not return cleanly.

    ``code`` is a short stable identifier — ``timeout`` |
    ``missing_binary`` | ``non_zero_exit`` | ``bad_input`` — that the
    dispatch loop maps onto the ``imessage.send.failed.{agent}`` payload.
    """

    def __init__(self, *, code: str, message: str, stderr: str = "") -> None:
        super().__init__(f"{code}: {message}")
        self.code = code
        self.message = message
        self.stderr = stderr


def _escape(value: str) -> str:
    """AppleScript string escaping. Reject newlines / null bytes upfront."""
    if "\n" in value or "\r" in value or "\x00" in value:
        raise OsascriptError(
            code="bad_input",
            message="AppleScript strings cannot contain newlines or null bytes.",
        )
    return value.replace("\\", "\\\\").replace('"', '\\"')


def send_imessage(
    *,
    to: str,
    body: str,
    service: str = "iMessage",
    timeout_s: float = DEFAULT_TIMEOUT_S,
) -> None:
    """Send one message. Raises ``OsascriptError`` on any failure path."""
    if service not in ("iMessage", "SMS"):
        raise OsascriptError(
            code="bad_input",
            message=f"Unsupported service: {service!r}.",
        )
    to_e = _escape(to)
    body_e = _escape(body)
    # Pick the named service; fall back to first matching.  For SMS the
    # service type is `SMS` and the buddy lookup is identical.
    script = (
        'tell application "Messages"\n'
        f"  set targetService to first service whose service type = {service}\n"
        f'  set targetBuddy to buddy "{to_e}" of targetService\n'
        f'  send "{body_e}" to targetBuddy\n'
        "end tell\n"
    )
    try:
        proc = subprocess.run(  # noqa: S603 — argv built from validated/escaped inputs
            [OSASCRIPT_BIN, "-e", script],
            capture_output=True,
            timeout=timeout_s,
            check=False,
        )
    except FileNotFoundError as exc:
        raise OsascriptError(
            code="missing_binary",
            message="osascript binary not found.",
        ) from exc
    except subprocess.TimeoutExpired as exc:
        raise OsascriptError(
            code="timeout",
            message=f"osascript timed out after {timeout_s}s.",
            stderr=(exc.stderr or b"").decode("utf-8", errors="replace")[:_STDERR_SNIPPET_LIMIT],
        ) from exc

    if proc.returncode != 0:
        stderr = proc.stderr.decode("utf-8", errors="replace")[:_STDERR_SNIPPET_LIMIT]
        raise OsascriptError(
            code="non_zero_exit",
            message=f"osascript exited with code {proc.returncode}.",
            stderr=stderr,
        )
    logger.debug("imessage_send_ok", extra={"to": to, "service": service})
