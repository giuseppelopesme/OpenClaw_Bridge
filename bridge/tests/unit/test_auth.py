"""Auth middleware: 401 on missing/bad token, 200 on a real one, 403 on missing scope."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from _support import TokenFixture
from bridge.auth import AuthContext, TokenStore, require_scope
from bridge.errors import ForbiddenScope, Unauthorized
from fastapi.testclient import TestClient

from bridge import auth as auth_module
from bridge import keychain


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
    tokens: list[TokenFixture],
) -> None:
    good = next(f for f in tokens if f.actor == "brain.clu")
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


def test_token_store_picks_up_new_keychain_entry_after_refresh(
    client: TestClient,
) -> None:
    """A token added to Keychain after startup is honoured after refresh()."""
    keychain.set_credential("cli.rotated", "new-rotated-token", ["admin"])
    # Bridge's TokenStore caches for 60s; force a refresh as the CLI tools do.
    store: TokenStore = client.app.state.token_store  # type: ignore[attr-defined]
    store.refresh()

    resp = client.get(
        "/v1/auth/whoami",
        headers={"Authorization": "Bearer new-rotated-token"},
    )
    assert resp.status_code == 200
    assert resp.json()["actor"] == "cli.rotated"


def test_token_store_refreshes_after_ttl_elapses(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """After REFRESH_TTL_SECONDS, the store transparently rebuilds on lookup."""
    store: TokenStore = client.app.state.token_store  # type: ignore[attr-defined]
    # Add a new credential after startup.
    keychain.set_credential("cli.delayed", "delayed-token", ["admin"])

    # Within TTL: not yet visible.
    resp_before = client.get(
        "/v1/auth/whoami",
        headers={"Authorization": "Bearer delayed-token"},
    )
    assert resp_before.status_code == 401

    # Force time forward past the TTL; lookup should rebuild and find it.
    fake_now = [10_000.0 + auth_module.REFRESH_TTL_SECONDS + 5]
    monkeypatch.setattr(auth_module.time, "monotonic", lambda: fake_now[0])
    # Reset the loaded_at to 10_000 so elapsed > TTL.
    store._loaded_at = 10_000.0  # noqa: SLF001 — direct cache poke for the test

    resp_after = client.get(
        "/v1/auth/whoami",
        headers={"Authorization": "Bearer delayed-token"},
    )
    assert resp_after.status_code == 200
    assert resp_after.json()["actor"] == "cli.delayed"


def test_rotation_grace_token_still_valid(client: TestClient) -> None:
    """During the grace window, the previous token still authenticates."""
    keychain.set_credential(
        "cli.rotator",
        "token-new",
        ["admin"],
        previous_token="token-old",
        previous_expires_at=datetime.now(UTC) + timedelta(hours=24),
    )
    store: TokenStore = client.app.state.token_store  # type: ignore[attr-defined]
    store.refresh()

    new = client.get(
        "/v1/auth/whoami",
        headers={"Authorization": "Bearer token-new"},
    )
    old = client.get(
        "/v1/auth/whoami",
        headers={"Authorization": "Bearer token-old"},
    )
    assert new.status_code == 200
    assert old.status_code == 200
    assert new.json()["actor"] == "cli.rotator"
    assert old.json()["actor"] == "cli.rotator"


def test_rotation_grace_token_expires(client: TestClient) -> None:
    keychain.set_credential(
        "cli.rotator",
        "token-new",
        ["admin"],
        previous_token="token-old",
        previous_expires_at=datetime.now(UTC) - timedelta(seconds=1),
    )
    store: TokenStore = client.app.state.token_store  # type: ignore[attr-defined]
    store.refresh()

    new = client.get("/v1/auth/whoami", headers={"Authorization": "Bearer token-new"})
    old = client.get("/v1/auth/whoami", headers={"Authorization": "Bearer token-old"})
    assert new.status_code == 200
    assert old.status_code == 401


def test_unauthorized_dataclass_carries_message() -> None:
    err = Unauthorized("reason here")
    assert err.code == "unauthorized"
    assert err.http_status == 401
    assert err.message == "reason here"
    assert err.details == {}
