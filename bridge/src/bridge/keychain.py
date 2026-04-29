"""macOS Keychain wrapper for bridge tokens.

One Keychain item per actor:

- service: the module-level `SERVICE_NAME` constant
  ("com.giuseppelopesme.openclaw.bridge")
- account: the actor identifier (e.g. "relay.clu", "brain.clu",
  "cli.giuseppelopes")
- password: a JSON blob shaped like

      {
        "token": "<hex>",
        "previous_token": "<hex>" | null,
        "previous_expires_at": "<iso8601 utc>" | null,
        "scopes": ["...", ...]
      }

`previous_token` and `previous_expires_at` carry the rotation grace window
documented in `docs/api-contract.md`: a freshly minted token replaces `token`,
and the prior value moves into `previous_token` until `previous_expires_at`.

Enumeration: Python's `keyring` API has no portable "list accounts under a
service" call, so we maintain our own manifest item under the same service with
account `_actors_` containing a JSON list. `set_credential` and
`delete_credential` keep it in sync.

Platform: this module is macOS-only in production. On any other platform it
raises `RuntimeError` at import time. Tests on every platform use the in-memory
fake backend wired through `bridge.tests.conftest`.

This module deliberately has zero FastAPI imports so CLI tools can use it
without dragging in the web stack.
"""

from __future__ import annotations

import contextlib
import json
import sys
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Final, Protocol

if sys.platform != "darwin":  # pragma: no cover - production constraint only
    raise RuntimeError(
        "bridge.keychain is macOS-only. Use the test fake backend on other platforms.",
    )

import keyring

SERVICE_NAME: Final[str] = "com.giuseppelopesme.openclaw.bridge"
_MANIFEST_ACCOUNT: Final[str] = "_actors_"


@dataclass(frozen=True)
class Credential:
    """One Keychain-backed token, including any rotation grace token."""

    actor: str
    token: str
    scopes: tuple[str, ...]
    previous_token: str | None = None
    previous_expires_at: datetime | None = None

    def previous_is_active(self, now: datetime | None = None) -> bool:
        if self.previous_token is None or self.previous_expires_at is None:
            return False
        current = now or datetime.now(UTC)
        return current < self.previous_expires_at


class _KeyringBackend(Protocol):
    """Minimal slice of `keyring`'s API we depend on. Lets us swap a fake in tests."""

    def get_password(self, service: str, username: str) -> str | None: ...
    def set_password(self, service: str, username: str, password: str) -> None: ...
    def delete_password(self, service: str, username: str) -> None: ...


# `keyring` exposes `set_password`, `get_password`, `delete_password` at the
# module level. They satisfy the `_KeyringBackend` protocol structurally.
_backend: _KeyringBackend = keyring


def _set_backend(backend: _KeyringBackend) -> None:
    """Test seam: swap the keyring backend (used by the in-memory fake)."""
    global _backend  # noqa: PLW0603 — single module-level seam by design
    _backend = backend


def _serialise(cred: Credential) -> str:
    body: dict[str, object] = {
        "token": cred.token,
        "scopes": list(cred.scopes),
    }
    if cred.previous_token is not None and cred.previous_expires_at is not None:
        body["previous_token"] = cred.previous_token
        body["previous_expires_at"] = cred.previous_expires_at.astimezone(UTC).isoformat()
    return json.dumps(body, ensure_ascii=False)


def _deserialise(actor: str, password: str) -> Credential | None:
    try:
        body = json.loads(password)
    except json.JSONDecodeError:
        return None
    if not isinstance(body, dict):
        return None
    token = body.get("token")
    scopes = body.get("scopes")
    if not isinstance(token, str) or not isinstance(scopes, list):
        return None
    parsed_scopes: tuple[str, ...] = tuple(s for s in scopes if isinstance(s, str))
    previous_token_raw = body.get("previous_token")
    previous_expires_raw = body.get("previous_expires_at")
    previous_token: str | None = previous_token_raw if isinstance(previous_token_raw, str) else None
    previous_expires_at: datetime | None = None
    if isinstance(previous_expires_raw, str):
        try:
            previous_expires_at = datetime.fromisoformat(previous_expires_raw)
        except ValueError:
            previous_expires_at = None
    return Credential(
        actor=actor,
        token=token,
        scopes=parsed_scopes,
        previous_token=previous_token,
        previous_expires_at=previous_expires_at,
    )


def _read_manifest() -> list[str]:
    raw = _backend.get_password(SERVICE_NAME, _MANIFEST_ACCOUNT)
    if raw is None:
        return []
    try:
        actors = json.loads(raw)
    except json.JSONDecodeError:
        return []
    if not isinstance(actors, list):
        return []
    return [a for a in actors if isinstance(a, str)]


def _write_manifest(actors: list[str]) -> None:
    _backend.set_password(
        SERVICE_NAME,
        _MANIFEST_ACCOUNT,
        json.dumps(sorted(set(actors)), ensure_ascii=False),
    )


def set_credential(
    actor: str,
    token: str,
    scopes: list[str],
    *,
    previous_token: str | None = None,
    previous_expires_at: datetime | None = None,
) -> None:
    """Write or overwrite the credential for `actor`. Updates the manifest."""
    if actor == _MANIFEST_ACCOUNT:
        msg = f"actor name '{_MANIFEST_ACCOUNT}' is reserved"
        raise ValueError(msg)
    cred = Credential(
        actor=actor,
        token=token,
        scopes=tuple(scopes),
        previous_token=previous_token,
        previous_expires_at=previous_expires_at,
    )
    _backend.set_password(SERVICE_NAME, actor, _serialise(cred))
    actors = _read_manifest()
    if actor not in actors:
        actors.append(actor)
        _write_manifest(actors)


def get_credential(actor: str) -> Credential | None:
    """Read one credential by actor."""
    if actor == _MANIFEST_ACCOUNT:
        return None
    raw = _backend.get_password(SERVICE_NAME, actor)
    if raw is None:
        return None
    return _deserialise(actor, raw)


def list_actors() -> list[str]:
    """Every actor with a credential under our service."""
    return sorted(_read_manifest())


def delete_credential(actor: str) -> None:
    """Remove the credential for `actor`. No-op if it does not exist."""
    if actor == _MANIFEST_ACCOUNT:
        msg = f"actor name '{_MANIFEST_ACCOUNT}' is reserved"
        raise ValueError(msg)
    # Item already absent — keyring on macOS raises rather than no-op.
    with contextlib.suppress(keyring.errors.PasswordDeleteError):
        _backend.delete_password(SERVICE_NAME, actor)
    actors = [a for a in _read_manifest() if a != actor]
    _write_manifest(actors)


def list_credentials() -> list[Credential]:
    """Every credential under our service. Skips entries that fail to parse."""
    out: list[Credential] = []
    for actor in list_actors():
        cred = get_credential(actor)
        if cred is not None:
            out.append(cred)
    return out
