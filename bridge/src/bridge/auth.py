"""Bearer-token authentication and scope checks.

Step 1 reads tokens from a JSON file at `~/.openclaw/tokens.dev.json` (path
configurable via `BRIDGE_TOKEN_STORE`). The file maps SHA-256 digests of the
plaintext token to `{actor, scopes[]}`. Real macOS Keychain integration replaces
this in a later step — the dependency surface (`require_auth`, `require_scope`)
will not change.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Annotated

from fastapi import Depends, Request

from bridge.errors import ForbiddenScope, Unauthorized


@dataclass(frozen=True)
class AuthContext:
    actor: str
    scopes: frozenset[str]


@dataclass(frozen=True)
class TokenRecord:
    actor: str
    scopes: frozenset[str]


class TokenStore:
    """Loads tokens from a dev JSON file. Reloads if the file mtime changes.

    The hot reload is intentional: token rotation needs to take effect inside
    the 24h grace window without restarting a long-running bridge.
    """

    def __init__(self, path: Path) -> None:
        self._path = path
        self._records: dict[str, TokenRecord] = {}
        self._loaded_mtime: float | None = None

    def reload(self) -> None:
        if not self._path.exists():
            self._records = {}
            self._loaded_mtime = 0.0
            return
        with self._path.open("r", encoding="utf-8") as fh:
            raw = json.load(fh)
        records: dict[str, TokenRecord] = {}
        if isinstance(raw, dict):
            for digest, body in raw.items():
                if not isinstance(digest, str) or not isinstance(body, dict):
                    continue
                actor = body.get("actor")
                scopes = body.get("scopes")
                if not isinstance(actor, str) or not isinstance(scopes, list):
                    continue
                records[digest] = TokenRecord(
                    actor=actor,
                    scopes=frozenset(s for s in scopes if isinstance(s, str)),
                )
        self._records = records
        self._loaded_mtime = self._path.stat().st_mtime

    def lookup(self, token: str) -> TokenRecord | None:
        try:
            mtime = self._path.stat().st_mtime if self._path.exists() else 0.0
        except OSError:
            mtime = 0.0
        if self._loaded_mtime is None or mtime != self._loaded_mtime:
            self.reload()
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
