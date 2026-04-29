"""Bearer-token authentication and scope checks.

Tokens live in macOS Keychain under service `com.giuseppelopesme.openclaw.bridge`,
one item per actor. The bridge enumerates them at startup, building an
in-memory map from `sha256(token)` to `(actor, scopes)`. Both the current token
and the rotation grace token (`previous_token`) are indexed.

### Refresh policy

The lookup map is refreshed lazily with a TTL of `REFRESH_TTL_SECONDS` (60s).
That means a freshly minted token can take up to one minute to be honoured by a
running bridge. The CLI tools `scripts/mint-token.py` and `scripts/rotate-token.py`
should call `TokenStore.refresh()` after writing so the change takes effect
immediately for the local process — eventual consistency only applies if the
bridge is running in another process.

Operationally: `set/rotate token` → notify bridge (e.g. via a future
`POST /v1/admin/refresh-tokens` endpoint, or process restart) → updated map.

### Removed in Session 3

The Session 1/2 transitional `~/.openclaw/tokens.dev.json` fallback was removed
in Session 3 — Keychain is the only token source. To populate Keychain on a
fresh host: `scripts/mint-token.py --actor <id> --scopes <a,b,c>`.
"""

from __future__ import annotations

import hashlib
import logging
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Annotated

from fastapi import Depends, Request

from bridge import keychain
from bridge.errors import ForbiddenScope, Unauthorized

logger = logging.getLogger("bridge.auth")

REFRESH_TTL_SECONDS: float = 60.0


@dataclass(frozen=True)
class AuthContext:
    actor: str
    scopes: frozenset[str]


@dataclass(frozen=True)
class TokenRecord:
    actor: str
    scopes: frozenset[str]


class TokenStore:
    """In-memory map of `sha256(token) -> TokenRecord`, sourced from Keychain.

    Build the map on first lookup (and on `refresh()`); cache for
    `REFRESH_TTL_SECONDS`. The cache is refreshed transparently on the next
    lookup after the TTL elapses.
    """

    def __init__(self) -> None:
        self._records: dict[str, TokenRecord] = {}
        self._loaded_at: float | None = None

    def refresh(self) -> None:
        """Force-rebuild the in-memory map from Keychain.

        Provider-style entries (account `provider.<name>`) are skipped — they
        store API keys for downstream services (OpenRouter, etc.) that do not
        authenticate inbound bridge requests.
        """
        records: dict[str, TokenRecord] = {}
        for cred in keychain.list_credentials():
            if cred.actor.startswith("provider."):
                continue
            self._index(records, cred.token, cred.actor, cred.scopes)
            if cred.previous_is_active():
                assert cred.previous_token is not None  # for type-checker
                self._index(records, cred.previous_token, cred.actor, cred.scopes)
        self._records = records
        self._loaded_at = time.monotonic()

    @staticmethod
    def _index(
        records: dict[str, TokenRecord],
        token: str,
        actor: str,
        scopes: tuple[str, ...] | frozenset[str],
    ) -> None:
        digest = hashlib.sha256(token.encode("utf-8")).hexdigest()
        records[digest] = TokenRecord(actor=actor, scopes=frozenset(scopes))

    def lookup(self, token: str) -> TokenRecord | None:
        if self._loaded_at is None or time.monotonic() - self._loaded_at > REFRESH_TTL_SECONDS:
            self.refresh()
        digest = hashlib.sha256(token.encode("utf-8")).hexdigest()
        return self._records.get(digest)


def require_auth(request: Request) -> AuthContext:
    """FastAPI dependency: validate bearer token, return AuthContext.

    Raises `Unauthorized` (401) on missing, malformed, or unknown token.
    Sets `request.state.actor` so the access-log middleware can pick it up.
    """
    store: TokenStore = request.app.state.token_store
    header = request.headers.get("authorization", "")
    if not header.lower().startswith("bearer "):
        raise Unauthorized("Missing or malformed Authorization header.")
    token = header[7:].strip()
    if not token:
        raise Unauthorized("Empty bearer token.")
    record = store.lookup(token)
    if record is None:
        raise Unauthorized("Unknown token.")
    request.state.actor = record.actor
    return AuthContext(actor=record.actor, scopes=record.scopes)


def require_scope(scope: str) -> Callable[..., AuthContext]:
    """Dependency factory: requires bearer auth AND the named scope."""

    def _check(auth: Annotated[AuthContext, Depends(require_auth)]) -> AuthContext:
        if scope not in auth.scopes:
            raise ForbiddenScope(f"Token lacks required scope: {scope}")
        return auth

    return _check
