"""FastAPI app factory and ASGI entry.

`bridge.main:app` is a fully-wired FastAPI app suitable for `uvicorn`. It does
not touch root logging — the production entry at `bridge.__main__` configures
JSON logging before booting uvicorn, while tests construct fresh apps via
`create_app()` without disturbing pytest's caplog.

App-state surface (set in lifespan, read by routes/middleware):

- `started_at`        — monotonic time, for `/v1/health` uptime
- `version`           — `bridge.__version__`
- `token_store`       — `auth.TokenStore` backed by macOS Keychain
- `idempotency_conn`  — sqlite3 connection backing the Idempotency middleware
- `rate_limiter`      — process-local token-bucket store
- `vault_provider`    — bound to `OBSIDIAN_VAULT` (or unconfigured)
"""

from __future__ import annotations

import logging
import time
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from bridge import __version__, errors
from bridge.auth import TokenStore
from bridge.config import Settings
from bridge.idempotency import IdempotencyMiddleware
from bridge.middleware import AccessLogMiddleware, RequestIDMiddleware
from bridge.migrations import open_with_migrations
from bridge.providers.vault import VaultProvider
from bridge.ratelimit import RateLimiter
from bridge.routes import auth as auth_routes
from bridge.routes import health as health_routes
from bridge.routes import vault as vault_routes


def create_app(settings: Settings | None = None) -> FastAPI:
    """Build a FastAPI app. Pure wiring — does not touch global logging."""
    cfg = settings or Settings.from_env()
    logger = logging.getLogger("bridge.startup")

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        app.state.started_at = time.monotonic()
        app.state.version = __version__
        app.state.token_store = TokenStore(fallback_path=cfg.token_store_path)
        app.state.token_store.refresh()
        app.state.idempotency_conn = open_with_migrations(
            cfg.idempotency_db_path,
            prefix="idempotency",
        )
        app.state.rate_limiter = RateLimiter()
        app.state.vault_provider = VaultProvider(cfg.vault_root)
        logger.info(
            "bridge_startup",
            extra={
                "version": __version__,
                "host": cfg.host,
                "port": cfg.port,
                "vault_configured": cfg.vault_root is not None,
            },
        )
        try:
            yield
        finally:
            conn = app.state.idempotency_conn
            if conn is not None:
                conn.close()
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

    return app


app = create_app()
