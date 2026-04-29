"""FastAPI app factory and ASGI entry.

`bridge.main:app` is a fully-wired FastAPI app suitable for `uvicorn`. It does
not touch root logging — the production entry at `bridge.__main__` configures
JSON logging before booting uvicorn, while tests construct fresh apps via
`create_app()` without disturbing pytest's caplog.
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
from bridge.middleware import AccessLogMiddleware, RequestIDMiddleware
from bridge.routes import auth as auth_routes
from bridge.routes import health as health_routes


def create_app(settings: Settings | None = None) -> FastAPI:
    """Build a FastAPI app. Pure wiring — does not touch global logging."""
    cfg = settings or Settings.from_env()
    logger = logging.getLogger("bridge.startup")

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        app.state.started_at = time.monotonic()
        app.state.version = __version__
        app.state.token_store = TokenStore(cfg.token_store_path)
        app.state.token_store.reload()
        logger.info(
            "bridge_startup",
            extra={"version": __version__, "host": cfg.host, "port": cfg.port},
        )
        yield
        logger.info("bridge_shutdown", extra={"version": __version__})

    app = FastAPI(
        title="OpenClaw Bridge",
        version=__version__,
        lifespan=lifespan,
    )

    # Inner middleware added first; RequestID ends up outermost so the access
    # log middleware can read the id stamped on `request.state.request_id`.
    app.add_middleware(AccessLogMiddleware)
    app.add_middleware(RequestIDMiddleware)

    errors.install(app)

    app.include_router(health_routes.router)
    app.include_router(auth_routes.router)

    return app


app = create_app()
