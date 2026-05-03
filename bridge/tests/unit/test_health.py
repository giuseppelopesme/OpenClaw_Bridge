"""GET /v1/health — happy path and shape match against the spec."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

EXPECTED_DEPS = {
    "redis",
    "apple_bridge",
    "imap_glysk",
    "imap_lopes",
    "imap_whilesum",
    "openrouter",
    # Real probes added in Session 3 (additive — see api-contract amendment):
    "keychain",
    "vault",
    "idempotency_db",
    "telemetry_db",
    # Added in P1a:
    "agent_db",
}


def test_health_returns_documented_shape(client: TestClient) -> None:
    resp = client.get("/v1/health")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "ok"
    assert body["version"] == "1.0.0"
    assert isinstance(body["uptime_s"], int)
    assert body["uptime_s"] >= 0
    assert set(body["deps"].keys()) == EXPECTED_DEPS
    assert all(v == "ok" for v in body["deps"].values())


def test_health_does_not_require_auth(client: TestClient) -> None:
    # No Authorization header — must still return 200 per the spec.
    resp = client.get("/v1/health")
    assert resp.status_code == 200


def test_health_response_advertises_bridge_version(client: TestClient) -> None:
    resp = client.get("/v1/health")
    assert resp.headers["X-Bridge-Version"] == "1.0.0"


def test_health_vault_down_when_root_missing(client: TestClient) -> None:
    """A vault path that no longer exists is critical -> overall down."""
    from pathlib import Path

    from bridge.providers.vault import VaultProvider

    client.app.state.vault_provider = VaultProvider(Path("/nonexistent/vault/path"))
    resp = client.get("/v1/health")
    assert resp.status_code == 200
    body = resp.json()
    assert body["deps"]["vault"] == "down"
    assert body["status"] == "down"


def test_health_vault_degraded_when_unconfigured(client: TestClient) -> None:
    """No OBSIDIAN_VAULT -> vault degraded (still critical -> overall degraded)."""
    from bridge.providers.vault import VaultProvider

    client.app.state.vault_provider = VaultProvider(None)
    resp = client.get("/v1/health")
    body = resp.json()
    assert body["deps"]["vault"] == "degraded"
    assert body["status"] == "degraded"


def test_health_openrouter_degraded_does_not_change_overall(client: TestClient) -> None:
    """OpenRouter is non-critical: degraded does not flap overall status off ok."""
    from bridge import keychain

    keychain.delete_credential("provider.openrouter")  # forces healthcheck "degraded"
    resp = client.get("/v1/health")
    body = resp.json()
    assert body["deps"]["openrouter"] == "degraded"
    assert body["status"] == "ok"


def test_health_telemetry_db_down_when_connection_closed(client: TestClient) -> None:
    """Critical SQLite dep down -> overall down."""
    client.app.state.telemetry_conn.close()
    resp = client.get("/v1/health")
    body = resp.json()
    assert body["deps"]["telemetry_db"] == "down"
    assert body["status"] == "down"


def test_health_apple_bridge_down_pushes_overall_down(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Apple is critical: a runner failure marks status down."""
    from bridge.errors import DependencyUnavailable
    from bridge.routes import health as health_module

    async def _explode(*_args: object, **_kwargs: object) -> str:
        raise DependencyUnavailable("apple bridge timeout", details={"timeout": True})

    monkeypatch.setattr(health_module, "run_osascript", _explode)
    resp = client.get("/v1/health")
    body = resp.json()
    assert body["deps"]["apple_bridge"] == "down"
    assert body["status"] == "down"
