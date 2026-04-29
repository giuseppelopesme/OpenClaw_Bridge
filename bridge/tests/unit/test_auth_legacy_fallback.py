"""The legacy ~/.openclaw/tokens.dev.json path is consulted only when Keychain is empty."""

from __future__ import annotations

import hashlib
import json
import logging
from collections.abc import Iterator
from pathlib import Path

import pytest
from _support import FakeKeyring
from bridge.config import Settings
from bridge.main import create_app
from fastapi import FastAPI
from fastapi.testclient import TestClient

from bridge import keychain


def _digest(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


@pytest.fixture
def empty_keychain(fake_keychain: FakeKeyring) -> FakeKeyring:
    fake_keychain.reset()
    keychain._set_backend(fake_keychain)
    return fake_keychain


@pytest.fixture
def legacy_store(tmp_path: Path) -> Path:
    body = {
        _digest("legacy-token"): {
            "actor": "cli.legacy",
            "scopes": ["admin"],
        },
    }
    path = tmp_path / "tokens.dev.json"
    path.write_text(json.dumps(body), encoding="utf-8")
    return path


@pytest.fixture
def legacy_app(
    tmp_path: Path,
    vault_root: Path,
    legacy_store: Path,
    empty_keychain: FakeKeyring,
) -> FastAPI:
    _ = empty_keychain  # silence unused-arg
    settings = Settings(
        host="127.0.0.1",
        port=8788,
        log_level="info",
        token_store_path=legacy_store,
        idempotency_db_path=tmp_path / "idempotency.db",
        vault_root=vault_root,
    )
    return create_app(settings)


@pytest.fixture
def legacy_client(legacy_app: FastAPI) -> Iterator[TestClient]:
    with TestClient(legacy_app) as c:
        yield c


def test_legacy_fallback_authenticates_when_keychain_empty(
    legacy_client: TestClient,
    caplog: pytest.LogCaptureFixture,
) -> None:
    resp = legacy_client.get(
        "/v1/auth/whoami",
        headers={"Authorization": "Bearer legacy-token"},
    )
    assert resp.status_code == 200
    assert resp.json() == {"actor": "cli.legacy", "scopes": ["admin"]}
    # The warning fires on every refresh while Keychain is empty. Trigger one
    # under caplog to assert the structured message.
    with caplog.at_level(logging.WARNING, logger="bridge.auth"):
        legacy_client.app.state.token_store.refresh()  # type: ignore[attr-defined]
    assert any(rec.message == "token_store_fallback_to_json" for rec in caplog.records)


def test_keychain_takes_precedence_over_legacy_file(
    legacy_client: TestClient,
) -> None:
    """Once Keychain is populated, the JSON fallback is ignored on next refresh."""
    # Verify legacy works first.
    resp1 = legacy_client.get(
        "/v1/auth/whoami",
        headers={"Authorization": "Bearer legacy-token"},
    )
    assert resp1.status_code == 200

    # Populate Keychain and force a refresh — bridge stops looking at JSON.
    keychain.set_credential("brain.real", "real-token", ["admin"])
    legacy_client.app.state.token_store.refresh()  # type: ignore[attr-defined]

    resp_legacy = legacy_client.get(
        "/v1/auth/whoami",
        headers={"Authorization": "Bearer legacy-token"},
    )
    resp_real = legacy_client.get(
        "/v1/auth/whoami",
        headers={"Authorization": "Bearer real-token"},
    )
    assert resp_legacy.status_code == 401  # legacy ignored
    assert resp_real.status_code == 200
