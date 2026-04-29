"""Shared fixtures for the bridge test suite.

The Keychain wrapper is patched globally with an in-memory fake before any
test runs (`autouse` session fixture). Tests never touch the real macOS
Keychain. The opt-in `macos_keychain` marker pulls the real backend back in
for one integration test (skipped by default — see `tests/README.md`).

Each test gets a fresh FastAPI app pointed at:
- a tempfile-backed legacy JSON store (used by `tests/unit/test_auth_legacy_fallback.py`)
- a tempfile vault root with at least one canned page
- a per-test SQLite idempotency DB

Tokens are written into the fake Keychain at fixture setup so the bridge
finds them via the normal `keychain.list_credentials()` path.
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest
from _support import FakeKeyring, TokenFixture
from bridge.config import Settings
from bridge.main import create_app
from fastapi import FastAPI
from fastapi.testclient import TestClient

from bridge import keychain

_fake_backend = FakeKeyring()


def pytest_configure(config: pytest.Config) -> None:
    config.addinivalue_line(
        "markers",
        "macos_keychain: integration test that touches the real macOS Keychain. "
        "Skipped by default; run with `-m macos_keychain` to opt in.",
    )


def pytest_collection_modifyitems(
    config: pytest.Config,
    items: list[pytest.Item],
) -> None:
    if config.getoption("-m"):
        # Caller explicitly selected a marker expression — let it through.
        return
    skip_macos = pytest.mark.skip(reason="macos_keychain integration test (opt-in)")
    for item in items:
        if "macos_keychain" in item.keywords:
            item.add_marker(skip_macos)


@pytest.fixture(autouse=True)
def fake_keychain() -> Iterator[FakeKeyring]:
    """Reset the fake Keychain backend between tests; never touches real Keychain."""
    _fake_backend.reset()
    keychain._set_backend(_fake_backend)
    try:
        yield _fake_backend
    finally:
        _fake_backend.reset()


@pytest.fixture
def tokens(fake_keychain: FakeKeyring) -> list[TokenFixture]:
    """Pre-populate the fake Keychain with a couple of canned identities."""
    _ = fake_keychain  # autouse already wired it; depend on it for ordering
    fixtures = [
        TokenFixture(
            plain="dev-token-clu",
            actor="brain.clu",
            scopes=("llm:call", "vault:read", "vault:write"),
        ),
        TokenFixture(plain="dev-token-empty", actor="cli.test", scopes=()),
    ]
    for f in fixtures:
        keychain.set_credential(f.actor, f.plain, list(f.scopes))
    return fixtures


@pytest.fixture
def vault_root(tmp_path: Path) -> Path:
    root = tmp_path / "vault"
    root.mkdir()
    (root / "Inbox").mkdir()
    (root / "Inbox" / "hello.md").write_text(
        "---\ntitle: Hello\n---\n\nBody content here.\n",
        encoding="utf-8",
    )
    return root


@pytest.fixture
def settings(tmp_path: Path, vault_root: Path, tokens: list[TokenFixture]) -> Settings:
    # Reference `tokens` so they are seeded before app startup.
    _ = tokens
    return Settings(
        host="127.0.0.1",
        port=8788,
        log_level="info",
        token_store_path=tmp_path / "tokens.dev.json",
        idempotency_db_path=tmp_path / "idempotency.db",
        vault_root=vault_root,
    )


@pytest.fixture
def app(settings: Settings) -> FastAPI:
    return create_app(settings)


@pytest.fixture
def client(app: FastAPI) -> Iterator[TestClient]:
    with TestClient(app) as c:
        yield c
