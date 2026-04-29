"""GET /v1/health — happy path and shape match against the spec."""

from __future__ import annotations

from fastapi.testclient import TestClient

EXPECTED_DEPS = {
    "redis",
    "apple_bridge",
    "imap_glysk",
    "imap_lopes",
    "imap_whilesum",
    "openrouter",
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
