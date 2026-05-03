"""FastAPI app factory and ASGI entry.

`bridge.main:app` is a fully-wired FastAPI app suitable for `uvicorn`. It does
not touch root logging — the production entry at `bridge.__main__` configures
JSON logging and the JSONL access-log file before booting uvicorn, while tests
construct fresh apps via `create_app()` without disturbing pytest's caplog.

App-state surface (set in lifespan, read by routes/middleware):

- `started_at`            — monotonic time, for `/v1/health` uptime
- `version`               — `bridge.__version__`
- `settings`              — frozen `Settings` snapshot
- `token_store`           — `auth.TokenStore` backed by macOS Keychain
- `idempotency_conn`      — sqlite3 connection backing the Idempotency middleware
- `telemetry_conn`        — sqlite3 connection backing LLM call telemetry
- `agent_conn`            — sqlite3 connection backing the agent-drafts table (P1a)
- `rate_limiter`          — Redis-backed token-bucket store (Session 4)
- `vault_provider`        — bound to `OBSIDIAN_VAULT` (or unconfigured)
- `openrouter_provider`   — OpenRouter HTTP client (shared `httpx.AsyncClient`)
- `llm_router`            — task_class → provider routing
- `redis_client`          — `redis.asyncio.Redis` shared by publisher + limiter
- `event_publisher`       — `EventPublisher` for routes that emit events
- `email_config`          — `EmailConfig` parsed from `email.toml`
- `email_imap_providers`  — `dict[str, IMAPProvider]` keyed by account name
- `email_smtp_providers`  — `dict[str, SMTPProvider]` keyed by account name
- `_http_client`          — module-private; closed on shutdown
"""

from __future__ import annotations

import logging
import time
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import httpx
from fastapi import FastAPI

from bridge import __version__, errors, keychain
from bridge.auth import TokenStore
from bridge.config import Settings
from bridge.errors import DependencyUnavailable
from bridge.eventbus import EventPublisher, build_redis_client
from bridge.idempotency import IdempotencyMiddleware
from bridge.middleware import AccessLogMiddleware, RequestIDMiddleware
from bridge.migrations import open_with_migrations
from bridge.providers.apple.calendar import CalendarProvider
from bridge.providers.apple.contacts import ContactsProvider
from bridge.providers.apple.reminders import RemindersProvider
from bridge.providers.email import (
    EmailConfig,
    IMAPProvider,
    SMTPProvider,
    load_email_config,
)
from bridge.providers.llm.openrouter import OpenRouterProvider
from bridge.providers.llm.router import LLMRouter
from bridge.providers.vault import VaultProvider
from bridge.ratelimit import RateLimiter
from bridge.routes import agent as agent_routes
from bridge.routes import auth as auth_routes
from bridge.routes import calendar as calendar_routes
from bridge.routes import contacts as contacts_routes
from bridge.routes import email as email_routes
from bridge.routes import events as events_routes
from bridge.routes import health as health_routes
from bridge.routes import imessage as imessage_routes
from bridge.routes import llm as llm_routes
from bridge.routes import reminders as reminders_routes
from bridge.routes import vault as vault_routes


def create_app(settings: Settings | None = None) -> FastAPI:
    """Build a FastAPI app. Pure wiring — does not touch global logging."""
    cfg = settings or Settings.from_env()
    logger = logging.getLogger("bridge.startup")

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        app.state.started_at = time.monotonic()
        app.state.version = __version__
        app.state.settings = cfg
        app.state.token_store = TokenStore()
        app.state.token_store.refresh()
        app.state.idempotency_conn = open_with_migrations(
            cfg.idempotency_db_path,
            prefix="idempotency",
        )
        app.state.telemetry_conn = open_with_migrations(
            cfg.telemetry_db_path,
            prefix="telemetry",
        )
        app.state.agent_conn = open_with_migrations(
            cfg.agent_db_path,
            prefix="agent",
        )
        app.state.vault_provider = VaultProvider(cfg.vault_root)

        # Apple providers — stateless wrappers around the osascript runner.
        # Constructed once; the integration tests opt-in to the real binary
        # via the `macos_apple` pytest marker.
        app.state.calendar_provider = CalendarProvider()
        app.state.reminders_provider = RemindersProvider()
        app.state.contacts_provider = ContactsProvider()

        # Email providers — one IMAP + one SMTP per account, built from
        # email.toml + Keychain. Missing config or missing password →
        # the provider entry is absent and routes return 502. Per-account
        # health probes still report "down" for these accounts so the
        # operator sees the gap on /v1/health.
        email_cfg: EmailConfig = load_email_config(cfg.email_config_path)
        imap_providers: dict[str, IMAPProvider] = {}
        smtp_providers: dict[str, SMTPProvider] = {}
        for name, account in email_cfg.accounts.items():
            cred = keychain.get_credential(f"provider.email.{name}")
            if cred is None or not cred.token:
                logger.warning(
                    "email_account_password_missing",
                    extra={"account": name, "hint": f"set Keychain provider.email.{name}"},
                )
                continue
            imap_providers[name] = IMAPProvider(account, cred.token)
            smtp_providers[name] = SMTPProvider(account, cred.token)
        app.state.email_config = email_cfg
        app.state.email_imap_providers = imap_providers
        app.state.email_smtp_providers = smtp_providers

        # Redis: client + publisher + Redis-backed rate limiter. If the
        # Keychain password is missing we boot anyway, with `redis_client`
        # = None — endpoints that need Redis will return 502, /v1/health
        # marks redis "down". Operational visibility lives in the
        # structured warning here.
        try:
            redis_client = build_redis_client(
                host=cfg.redis_host,
                port=cfg.redis_port,
                db=cfg.redis_db,
            )
        except DependencyUnavailable:
            logger.warning(
                "redis_password_missing",
                extra={"hint": "set Keychain provider.redis"},
            )
            redis_client = None

        app.state.redis_client = redis_client
        app.state.event_publisher = (
            EventPublisher(redis_client) if redis_client is not None else None
        )
        app.state.rate_limiter = RateLimiter(redis_client)

        http_client = httpx.AsyncClient(timeout=30.0)
        app.state._http_client = http_client  # noqa: SLF001 — lifecycle owner
        app.state.openrouter_provider = OpenRouterProvider(http_client)
        app.state.llm_router = LLMRouter(
            openrouter=app.state.openrouter_provider,
            local=None,  # session-4+ slot
        )

        logger.info(
            "bridge_startup",
            extra={
                "version": __version__,
                "host": cfg.host,
                "port": cfg.port,
                "vault_configured": cfg.vault_root is not None,
                "redis_configured": redis_client is not None,
            },
        )

        # system.bridge.startup — best-effort. If Redis is unreachable we log
        # a structured warning and keep going.
        if app.state.event_publisher is not None:
            try:
                await app.state.event_publisher.publish(
                    "system.bridge.startup",
                    {"version": __version__, "started_at": time.time()},
                    publisher="bridge",
                )
            except DependencyUnavailable as exc:
                logger.warning(
                    "system_bridge_startup_publish_failed",
                    extra={"error": exc.message},
                )

        try:
            yield
        finally:
            for conn in (
                app.state.idempotency_conn,
                app.state.telemetry_conn,
                app.state.agent_conn,
            ):
                if conn is not None:
                    conn.close()
            await http_client.aclose()
            if redis_client is not None:
                await redis_client.aclose()
            logger.info("bridge_shutdown", extra={"version": __version__})

    app = FastAPI(
        title="OpenClaw Bridge",
        version=__version__,
        lifespan=lifespan,
    )

    # Inner middleware added first; RequestID ends up outermost so the access
    # log middleware can read the id stamped on `request.state.request_id`,
    # and the idempotency middleware sits inside RequestID so cached responses
    # still get fresh request ids stamped.
    app.add_middleware(IdempotencyMiddleware)
    app.add_middleware(AccessLogMiddleware)
    app.add_middleware(RequestIDMiddleware)

    errors.install(app)

    app.include_router(health_routes.router)
    app.include_router(auth_routes.router)
    app.include_router(vault_routes.router)
    app.include_router(llm_routes.router)
    app.include_router(events_routes.router)
    app.include_router(calendar_routes.router)
    app.include_router(reminders_routes.router)
    app.include_router(contacts_routes.router)
    app.include_router(email_routes.router)
    app.include_router(imessage_routes.router)
    app.include_router(agent_routes.router)

    return app


app = create_app()
