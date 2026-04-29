"""Idempotency-Key: replay returns cached body, mismatched body returns 409, TTL prunes."""

from __future__ import annotations

import time

import pytest
from _support import TokenFixture
from fastapi.testclient import TestClient

from bridge import idempotency

AUTH_HEADER_FOR_VAULT = "Bearer dev-token-clu"


def _vault_write_payload(
    path: str = "Inbox/idempotency.md",
    content: str = "hi",
) -> dict[str, object]:
    return {"path": path, "mode": "create", "content": content}


def test_post_without_idempotency_key_executes_normally(
    client: TestClient,
    tokens: list[TokenFixture],  # noqa: ARG001 — seeds keychain
) -> None:
    payload = _vault_write_payload("Inbox/no-key.md", "hello")
    resp = client.post(
        "/v1/vault/write",
        json=payload,
        headers={"Authorization": AUTH_HEADER_FOR_VAULT},
    )
    assert resp.status_code == 201
    assert "X-Idempotency-Replay" not in resp.headers


def test_idempotency_replay_returns_cached_response(
    client: TestClient,
    tokens: list[TokenFixture],  # noqa: ARG001
) -> None:
    payload = _vault_write_payload("Inbox/cached.md", "first content")
    headers = {
        "Authorization": AUTH_HEADER_FOR_VAULT,
        "Idempotency-Key": "k-replay",
    }
    r1 = client.post("/v1/vault/write", json=payload, headers=headers)
    assert r1.status_code == 201

    # Same key, same body — replay path. The second call must NOT re-create
    # the file (which would fail with 409 conflict if it were re-executed).
    r2 = client.post("/v1/vault/write", json=payload, headers=headers)
    assert r2.status_code == 201
    assert r2.headers.get("X-Idempotency-Replay") == "true"
    assert r2.json() == r1.json()


def test_idempotency_mismatched_body_returns_409(
    client: TestClient,
    tokens: list[TokenFixture],  # noqa: ARG001
) -> None:
    headers = {
        "Authorization": AUTH_HEADER_FOR_VAULT,
        "Idempotency-Key": "k-mismatch",
    }
    r1 = client.post(
        "/v1/vault/write",
        json=_vault_write_payload("Inbox/m1.md", "one"),
        headers=headers,
    )
    assert r1.status_code == 201

    r2 = client.post(
        "/v1/vault/write",
        json=_vault_write_payload("Inbox/m1.md", "TWO"),  # different body
        headers=headers,
    )
    assert r2.status_code == 409
    assert r2.json()["error"]["code"] == "idempotency_replay"


def test_idempotency_ttl_prunes_expired_entries(
    client: TestClient,
    tokens: list[TokenFixture],  # noqa: ARG001
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    headers = {
        "Authorization": AUTH_HEADER_FOR_VAULT,
        "Idempotency-Key": "k-expire",
    }
    payload = _vault_write_payload("Inbox/expire.md", "v1")
    r1 = client.post("/v1/vault/write", json=payload, headers=headers)
    assert r1.status_code == 201

    # Jump time forward past the 24h TTL — the cache row is pruned on next lookup.
    real_time = time.time
    fake_now = real_time() + idempotency.TTL_SECONDS + 60
    monkeypatch.setattr(idempotency.time, "time", lambda: fake_now)

    # Same key + same body, but row is gone → cache miss → re-executes.
    # Re-creating the same path is a 409 conflict from the vault provider,
    # not the idempotency replay path. That distinguishes the two cases.
    r2 = client.post("/v1/vault/write", json=payload, headers=headers)
    assert r2.status_code == 409
    assert r2.json()["error"]["code"] == "conflict"


def test_idempotency_skips_non_post_methods(
    client: TestClient,
    tokens: list[TokenFixture],  # noqa: ARG001
) -> None:
    """GET requests with the header just pass through — no caching."""
    resp = client.get(
        "/v1/vault/read?path=Inbox/hello.md",
        headers={
            "Authorization": AUTH_HEADER_FOR_VAULT,
            "Idempotency-Key": "should-be-ignored",
        },
    )
    assert resp.status_code == 200
    assert "X-Idempotency-Replay" not in resp.headers
