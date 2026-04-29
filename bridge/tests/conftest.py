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
        # Tests do not start a real Redis. The bridge boots cleanly with
        # `redis_client=None` (Keychain has no provider.redis entry by
        # default in the fake), and the rate limiter falls back to its
        # in-process bucket map. Tests that exercise the Redis path
        # explicitly install a fakeredis client into app.state.
        redis_host="127.0.0.1",
        redis_port=6379,
        redis_db=0,
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
    """Build a fresh FastAPI app. The lifespan body wires real services;
    the `client` fixture then swaps in fakes so tests are hermetic."""
    instance = create_app(settings)
    yield instance


@pytest.fixture
def client(app: FastAPI) -> Iterator[TestClient]:
    """Hermetic TestClient: fake OpenRouter, fake Redis, no network."""
    import asyncio

    import fakeredis.aioredis
    from bridge.eventbus import EventPublisher
    from bridge.ratelimit import RateLimiter

    with TestClient(app) as c:
        # OpenRouter — swap the real httpx client for a MockTransport.
        original_or = app.state.openrouter_provider
        mock_client = httpx.AsyncClient(transport=httpx.MockTransport(_default_mock_handler))
        app.state.openrouter_provider = OpenRouterProvider(mock_client)
        app.state.llm_router._openrouter = app.state.openrouter_provider  # noqa: SLF001

        # Redis — swap whatever the lifespan picked (likely None, since the
        # default fixture doesn't seed provider.redis) for an in-process
        # fake. The fake supports pubsub and our EVAL-based Lua, so the
        # rate limiter and event bus tests run end-to-end without touching
        # a live daemon.
        original_redis = app.state.redis_client
        original_publisher = app.state.event_publisher
        original_limiter = app.state.rate_limiter

        fake = fakeredis.aioredis.FakeRedis(decode_responses=False)
        app.state.redis_client = fake
        app.state.event_publisher = EventPublisher(fake)
        app.state.rate_limiter = RateLimiter(fake)

        try:
            yield c
        finally:
            asyncio.run(mock_client.aclose())
            asyncio.run(fake.aclose())
            app.state.openrouter_provider = original_or
            app.state.redis_client = original_redis
            app.state.event_publisher = original_publisher
            app.state.rate_limiter = original_limiter
