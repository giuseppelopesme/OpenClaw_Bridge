"""Read the relay token from the local user's login keychain.

The .app bundle has no shell wrapper to plumb ``RELAY_TOKEN`` from the
keychain into the env (Session 7's ``scripts/run-relay.sh`` did that). So
the relay reads the token itself, on startup, via the macOS ``security``
binary — same generic-password slot ``setup-relay-account.sh`` writes.

We deliberately avoid the ``keyring`` Python library to keep PyInstaller's
dependency closure tight and to mirror the rest of the project's
"shell out to Apple binaries" pattern (CLAUDE.md: "Apple integration uses
osascript subprocesses").
"""

from __future__ import annotations

import logging
import subprocess
from typing import Final

logger = logging.getLogger("relay.keychain")

_SECURITY_BIN: Final[str] = "/usr/bin/security"
_KEYCHAIN_SERVICE: Final[str] = "me.lopes.openclaw.bridge"
_DEFAULT_TIMEOUT_S: Final[float] = 5.0


class KeychainReadError(Exception):
    """Raised when the keychain item is missing or unreadable."""


def read_relay_token(actor: str, *, timeout_s: float = _DEFAULT_TIMEOUT_S) -> str:
    """Return the plaintext relay token stored under ``actor``.

    The slot is created by ``scripts/setup-relay-account.sh`` (or by the
    operator running ``security add-generic-password`` directly). The
    payload is a JSON envelope ``{"token": "...", "scopes": [...]}`` —
    we extract the ``token`` field. Raises ``KeychainReadError`` on any
    failure path (missing slot, unreadable, malformed JSON).
    """
    try:
        proc = subprocess.run(  # noqa: S603 — argv is hardcoded
            [
                _SECURITY_BIN,
                "find-generic-password",
                "-s",
                _KEYCHAIN_SERVICE,
                "-a",
                actor,
                "-w",
            ],
            capture_output=True,
            timeout=timeout_s,
            check=False,
        )
    except FileNotFoundError as exc:
        raise KeychainReadError(
            f"{_SECURITY_BIN} not found — running on a non-macOS host?",
        ) from exc
    except subprocess.TimeoutExpired as exc:
        raise KeychainReadError(
            f"keychain read timed out after {timeout_s}s",
        ) from exc

    if proc.returncode != 0:
        stderr = proc.stderr.decode("utf-8", errors="replace").strip()
        raise KeychainReadError(
            f"no keychain item for service={_KEYCHAIN_SERVICE!r} account={actor!r}: {stderr}",
        )

    payload = proc.stdout.decode("utf-8", errors="replace").strip()
    if not payload:
        raise KeychainReadError(f"empty keychain payload for account={actor!r}")

    # Payload is JSON ``{"token": "...", "scopes": [...]}``. Parse with the
    # stdlib so we do not pull a JSON library into the bundle for one read.
    import json  # noqa: PLC0415 — local import keeps cold-import path tiny

    try:
        envelope = json.loads(payload)
    except json.JSONDecodeError as exc:
        raise KeychainReadError(
            f"keychain payload for account={actor!r} is not valid JSON",
        ) from exc

    token = envelope.get("token") if isinstance(envelope, dict) else None
    if not isinstance(token, str) or not token:
        raise KeychainReadError(
            f"keychain payload for account={actor!r} has no 'token' field",
        )
    return token
