"""Shared fixtures for the bridge test suite.

The Keychain wrapper is patched globally with an in-memory fake before any
test runs (`autouse` session fixture). Tests never touch the real macOS
Keychain. The opt-in `macos_keychain` marker pulls the real backend back in
for one integration test (skipped by default — see `tests/README.md`).

Each test gets a fresh FastAPI app pointed at:
- a tempfile vault root with at least one canned page
- per-test SQLite files for idempotency and telemetry

The OpenRouter provider is rewired with an `httpx.MockTransport` that
short-circuits every real network call. LLM-route tests further override
`app.state.llm_router` with a fake provider via the `fake_llm_router`
fixture so tests assert routing without touching httpx at all.

Tokens are written into the fake Keychain at fixture setup so the bridge
finds them via the normal `keychain.list_credentials()` path.
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import httpx
import pytest
from _support import FakeKeyring, TokenFixture
from bridge.config import Settings
from bridge.main import create_app
from bridge.providers.llm.openrouter import OpenRouterProvider
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
    """Pre-populate the fake Keychain with a couple of canned identities and
    a stub OpenRouter provider key so the default health-check path reports
    ok. Tests that want to force the degraded branch clear the provider entry."""
    _ = fake_keychain
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
    keychain.set_credential("provider.openrouter", "fake-test-or-key", [])
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
    _ = tokens
    return Settings(
        host="127.0.0.1",
        port=8788,
        log_level="info",
        idempotency_db_path=tmp_path / "idempotency.db",
        telemetry_db_path=tmp_path / "telemetry.db",
        access_log_path=tmp_path / "access.log",
        vault_root=vault_root,
    )


def _default_mock_handler(request: httpx.Request) -> httpx.Response:
    """Default httpx MockTransport: lets `/models` return 200 (so health is ok)
    and any other call return a benign 200 chat completion. Tests that need
    different OpenRouter behaviour install their own transport via
    `replace_openrouter_transport`."""
    if request.url.path.endswith("/models"):
        return httpx.Response(200, json={"data": []})
    if request.url.path.endswith("/chat/completions"):
        return httpx.Response(
            200,
            json={
                "id": "chatcmpl-mock",
                "model": "anthropic/claude-haiku-4.5",
                "choices": [
                    {
                        "message": {"role": "assistant", "content": "mocked reply"},
                        "finish_reason": "stop",
                    },
                ],
                "usage": {"prompt_tokens": 10, "completion_tokens": 5},
            },
        )
    return httpx.Response(404)


@pytest.fixture
def app(settings: Settings) -> Iterator[FastAPI]:
    """Build a fresh FastAPI app and rewire the OpenRouter provider's httpx
    client so it cannot reach the real network."""
    instance = create_app(settings)
    yield instance


@pytest.fixture
def client(app: FastAPI) -> Iterator[TestClient]:
    with TestClient(app) as c:
        # Rewire OpenRouter to a MockTransport AFTER lifespan has installed
        # the provider. `transport` swaps cleanly because we wrap a fresh
        # AsyncClient — the original one is closed on shutdown.
        original = app.state.openrouter_provider
        mock_client = httpx.AsyncClient(transport=httpx.MockTransport(_default_mock_handler))
        app.state.openrouter_provider = OpenRouterProvider(mock_client)
        # Rewire the LLMRouter too so it points at the new provider.
        app.state.llm_router._openrouter = app.state.openrouter_provider  # noqa: SLF001
        try:
            yield c
        finally:
            # Async close inside sync teardown — schedule on the loop the
            # TestClient ran on. asyncio.run is fine here.
            import asyncio

            asyncio.run(mock_client.aclose())
            app.state.openrouter_provider = original
