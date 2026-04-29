"""Auth middleware: 401 on missing/bad token, 200 on a real one, 403 on missing scope."""

from __future__ import annotations

import hashlib
import json
import os
import time
from pathlib import Path
from typing import Any

import pytest
from bridge.auth import AuthContext, require_scope
from bridge.config import Settings
from bridge.errors import ForbiddenScope, Unauthorized
from bridge.main import create_app
from fastapi.testclient import TestClient


def test_protected_endpoint_returns_401_envelope_without_token(client: TestClient) -> None:
    resp = client.get("/v1/auth/whoami")
    assert resp.status_code == 401
    body = resp.json()
    assert body == {
        "error": {
            "code": "unauthorized",
            "message": "Missing or malformed Authorization header.",
            "details": {},
            "request_id": resp.headers["X-Request-ID"],
        },
    }


def test_protected_endpoint_returns_401_for_unknown_token(client: TestClient) -> None:
    resp = client.get("/v1/auth/whoami", headers={"Authorization": "Bearer nope"})
    assert resp.status_code == 401
    assert resp.json()["error"]["code"] == "unauthorized"


def test_protected_endpoint_returns_401_for_malformed_header(client: TestClient) -> None:
    resp = client.get("/v1/auth/whoami", headers={"Authorization": "Token abc"})
    assert resp.status_code == 401
    assert resp.json()["error"]["code"] == "unauthorized"


def test_protected_endpoint_returns_200_with_valid_token(
    client: TestClient,
    tokens: tuple[Path, list[Any]],
) -> None:
    _, fixtures = tokens
    good = next(f for f in fixtures if f.actor == "brain.clu")
    resp = client.get(
        "/v1/auth/whoami",
        headers={"Authorization": f"Bearer {good.plain}"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body == {"actor": "brain.clu", "scopes": sorted(good.scopes)}


def test_require_scope_raises_forbidden_when_scope_missing() -> None:
    """Unit test the scope-check dependency without spinning up a full route."""
    check = require_scope("admin")
    auth = AuthContext(actor="brain.clu", scopes=frozenset({"llm:call"}))
    with pytest.raises(ForbiddenScope) as exc_info:
        check(auth)
    assert "admin" in str(exc_info.value)


def test_require_scope_passes_when_scope_present() -> None:
    check = require_scope("llm:call")
    auth = AuthContext(actor="brain.clu", scopes=frozenset({"llm:call"}))
    result = check(auth)
    assert result is auth


def test_token_store_hot_reloads_on_mtime_change(tokens: tuple[Path, list[Any]]) -> None:
    """Adding a new token to the file should be picked up without a restart."""
    path, _ = tokens
    settings = Settings(
        host="127.0.0.1",
        port=8788,
        log_level="info",
        token_store_path=path,
    )
    app = create_app(settings)
    with TestClient(app) as c:
        # Initial state: dev-token-clu works.
        r1 = c.get("/v1/auth/whoami", headers={"Authorization": "Bearer dev-token-clu"})
        assert r1.status_code == 200

        # Append a new token, bump mtime, and verify the bridge sees it.
        existing = json.loads(path.read_text())
        existing[hashlib.sha256(b"new-rotated-token").hexdigest()] = {
            "actor": "cli.rotated",
            "scopes": ["admin"],
        }
        path.write_text(json.dumps(existing))
        # Force a distinct mtime — same-second writes on macOS may collide.
        future = time.time() + 1
        os.utime(path, (future, future))

        r2 = c.get(
            "/v1/auth/whoami",
            headers={"Authorization": "Bearer new-rotated-token"},
        )
        assert r2.status_code == 200
        assert r2.json()["actor"] == "cli.rotated"


def test_unauthorized_dataclass_carries_message() -> None:
    err = Unauthorized("reason here")
    assert err.code == "unauthorized"
    assert err.http_status == 401
    assert err.message == "reason here"
    assert err.details == {}
