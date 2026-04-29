"""Vault HTTP endpoints: scope enforcement, read shape, write modes, vault.changed log."""

from __future__ import annotations

import logging

import pytest
from _support import TokenFixture
from fastapi.testclient import TestClient

AUTH_OK = {"Authorization": "Bearer dev-token-clu"}


def test_vault_read_happy_path(
    client: TestClient,
    tokens: list[TokenFixture],  # noqa: ARG001
) -> None:
    resp = client.get("/v1/vault/read?path=Inbox/hello.md", headers=AUTH_OK)
    assert resp.status_code == 200
    body = resp.json()
    assert body["path"] == "Inbox/hello.md"
    assert "Body content here." in body["content"]
    assert body["frontmatter"] == {"title": "Hello"}
    assert body["size"] > 0


def test_vault_read_returns_404_for_missing(
    client: TestClient,
    tokens: list[TokenFixture],  # noqa: ARG001
) -> None:
    resp = client.get("/v1/vault/read?path=Inbox/nope.md", headers=AUTH_OK)
    assert resp.status_code == 404
    assert resp.json()["error"]["code"] == "not_found"


def test_vault_read_requires_scope(client: TestClient) -> None:
    """A token without vault:read gets 403."""
    # dev-token-empty has zero scopes.
    resp = client.get(
        "/v1/vault/read?path=Inbox/hello.md",
        headers={"Authorization": "Bearer dev-token-empty"},
    )
    assert resp.status_code == 403
    assert resp.json()["error"]["code"] == "forbidden_scope"


def test_vault_read_path_traversal_returns_400(
    client: TestClient,
    tokens: list[TokenFixture],  # noqa: ARG001
) -> None:
    resp = client.get("/v1/vault/read?path=../escape.md", headers=AUTH_OK)
    assert resp.status_code == 400
    assert resp.json()["error"]["code"] == "bad_request"


def test_vault_write_create_returns_201_and_logs_changed(
    client: TestClient,
    tokens: list[TokenFixture],  # noqa: ARG001
    caplog: pytest.LogCaptureFixture,
) -> None:
    payload = {
        "path": "Inbox/new.md",
        "mode": "create",
        "content": "fresh\n",
        "frontmatter": {"created": "2026-04-29"},
    }
    with caplog.at_level(logging.INFO, logger="bridge.vault"):
        resp = client.post("/v1/vault/write", json=payload, headers=AUTH_OK)
    assert resp.status_code == 201
    body = resp.json()
    assert body["path"] == "Inbox/new.md"
    assert body["size"] > 0
    # Round-trip through the read endpoint.
    rd = client.get("/v1/vault/read?path=Inbox/new.md", headers=AUTH_OK).json()
    assert rd["frontmatter"] == {"created": "2026-04-29"}
    assert "fresh" in rd["content"]
    # Structured log line for vault.changed.
    matches = [
        rec
        for rec in caplog.records
        if rec.message == "vault.changed" and rec.__dict__.get("op") == "create"
    ]
    assert matches, "expected vault.changed log line"
    assert matches[0].__dict__.get("path") == "Inbox/new.md"
    assert matches[0].__dict__.get("actor") == "brain.clu"


def test_vault_write_replace_returns_200(
    client: TestClient,
    tokens: list[TokenFixture],  # noqa: ARG001
) -> None:
    client.post(
        "/v1/vault/write",
        json={"path": "Inbox/r.md", "mode": "create", "content": "v1\n"},
        headers=AUTH_OK,
    )
    resp = client.post(
        "/v1/vault/write",
        json={"path": "Inbox/r.md", "mode": "replace", "content": "v2\n"},
        headers=AUTH_OK,
    )
    assert resp.status_code == 200


def test_vault_write_append_returns_200_and_extends(
    client: TestClient,
    tokens: list[TokenFixture],  # noqa: ARG001
) -> None:
    payload1 = {"path": "Inbox/a.md", "mode": "append", "content": "first\n"}
    payload2 = {"path": "Inbox/a.md", "mode": "append", "content": "second\n"}
    r1 = client.post("/v1/vault/write", json=payload1, headers=AUTH_OK)
    r2 = client.post("/v1/vault/write", json=payload2, headers=AUTH_OK)
    assert r1.status_code == 200
    assert r2.status_code == 200
    body = client.get("/v1/vault/read?path=Inbox/a.md", headers=AUTH_OK).json()
    assert "first" in body["content"]
    assert "second" in body["content"]


def test_vault_write_create_existing_returns_409(
    client: TestClient,
    tokens: list[TokenFixture],  # noqa: ARG001
) -> None:
    payload = {"path": "Inbox/dup.md", "mode": "create", "content": "x"}
    client.post("/v1/vault/write", json=payload, headers=AUTH_OK)
    resp = client.post("/v1/vault/write", json=payload, headers=AUTH_OK)
    assert resp.status_code == 409
    assert resp.json()["error"]["code"] == "conflict"


def test_vault_write_replace_missing_returns_404(
    client: TestClient,
    tokens: list[TokenFixture],  # noqa: ARG001
) -> None:
    resp = client.post(
        "/v1/vault/write",
        json={"path": "Inbox/missing.md", "mode": "replace", "content": "x"},
        headers=AUTH_OK,
    )
    assert resp.status_code == 404


def test_vault_write_requires_scope(client: TestClient) -> None:
    resp = client.post(
        "/v1/vault/write",
        json={"path": "Inbox/x.md", "mode": "create", "content": "x"},
        headers={"Authorization": "Bearer dev-token-empty"},
    )
    assert resp.status_code == 403
