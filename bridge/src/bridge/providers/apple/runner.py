"""Single async helper that drives `osascript` for the Apple providers.

Every Apple provider funnels through `run_osascript`. That keeps the test
seam in one place: unit tests monkeypatch this function to return canned
strings; integration tests opt in via the `macos_apple` pytest marker
and exercise the real binary.

Error mapping:

- exit 0           → return decoded stdout, stripped
- non-zero exit    → DependencyUnavailable, with details.stderr (first 500 chars)
- timeout          → DependencyUnavailable, details.timeout=True
- missing binary   → DependencyUnavailable, details.missing="osascript"
- decode failure   → DependencyUnavailable, details.decode_error=True

Apple's TCC (Privacy & Security) prompts on first contact with Calendar,
Reminders, and Contacts. The bridge cannot dismiss those — operators grant
once per resource. See SESSION-NOTES.md "First-run TCC permission grants".
"""

from __future__ import annotations

import asyncio
import logging

from bridge.errors import DependencyUnavailable

logger = logging.getLogger("bridge.providers.apple.runner")

OSASCRIPT_BIN: str = "osascript"
DEFAULT_TIMEOUT_S: float = 10.0
_STDERR_SNIPPET_LIMIT: int = 500


async def run_osascript(script: str, *, timeout_s: float = DEFAULT_TIMEOUT_S) -> str:
    """Execute an AppleScript snippet via `osascript -e`. Return stripped stdout.

    Raises `DependencyUnavailable` on timeout, non-zero exit, or missing binary.
    The error envelope includes the stderr snippet so callers (and ops) can
    see what AppleScript complained about — usually a TCC denial or a wrong
    object reference.
    """
    try:
        proc = await asyncio.create_subprocess_exec(
            OSASCRIPT_BIN,
            "-e",
            script,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
    except FileNotFoundError as exc:
        raise DependencyUnavailable(
            "osascript binary not found.",
            details={"missing": OSASCRIPT_BIN},
        ) from exc

    try:
        stdout_b, stderr_b = await asyncio.wait_for(
            proc.communicate(),
            timeout=timeout_s,
        )
    except TimeoutError as exc:
        proc.kill()
        # Drain to release the subprocess slots cleanly.
        try:
            await proc.wait()
        except Exception:  # noqa: BLE001 — best-effort cleanup
            logger.debug("osascript_kill_swallowed", exc_info=True)
        raise DependencyUnavailable(
            "osascript timed out.",
            details={"timeout": True, "timeout_s": timeout_s},
        ) from exc

    if proc.returncode != 0:
        stderr_snip = stderr_b.decode("utf-8", errors="replace")[:_STDERR_SNIPPET_LIMIT]
        raise DependencyUnavailable(
            "osascript exited non-zero.",
            details={
                "exit_code": proc.returncode,
                "stderr": stderr_snip,
            },
        )

    try:
        return stdout_b.decode("utf-8").strip()
    except UnicodeDecodeError as exc:
        raise DependencyUnavailable(
            "osascript stdout was not valid utf-8.",
            details={"decode_error": True},
        ) from exc
