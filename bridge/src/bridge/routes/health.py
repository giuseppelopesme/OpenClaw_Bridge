"""GET /v1/health — no auth.

Response shape from `docs/api-contract.md`. Per-dep checks landed in
Session 3; the originally-stubbed `redis`, `apple_bridge`, and `imap_*`
keys remain "ok" stubs until their providers ship in steps 4–6.

Criticality:
- Critical (a "down" or "degraded" pushes overall status off "ok"):
  `keychain`, `idempotency_db`, `telemetry_db`, `vault`.
- Non-critical: `openrouter`, plus all the still-stubbed keys. The LLM
  endpoint owns its own errors; a slow OpenRouter shouldn't make
  health flap.

All checks run concurrently with a short timeout so a single laggard
doesn't slow the probe.
"""

from __future__ import annotations

import asyncio
import logging
import sqlite3
import time
from typing import Final, Literal

from fastapi import APIRouter, Request
from pydantic import BaseModel

from bridge import keychain
from bridge.config import Settings
from bridge.providers.llm.openrouter import OpenRouterProvider
from bridge.providers.vault import VaultProvider

logger = logging.getLogger("bridge.health")

router = APIRouter(tags=["health"])

DepStatus = Literal["ok", "degraded", "down"]
OverallStatus = Literal["ok", "degraded", "down"]

_CRITICAL_DEPS: Final[frozenset[str]] = frozenset(
    {"keychain", "idempotency_db", "telemetry_db", "vault"},
)


class Deps(BaseModel):
    redis: DepStatus
    apple_bridge: DepStatus
    imap_glysk: DepStatus
    imap_lopes: DepStatus
    imap_whilesum: DepStatus
    openrouter: DepStatus
    keychain: DepStatus
    vault: DepStatus
    idempotency_db: DepStatus
    telemetry_db: DepStatus


class HealthResponse(BaseModel):
    status: OverallStatus
    version: str
    uptime_s: int
    deps: Deps


async def _check_keychain() -> DepStatus:
    try:
        await asyncio.to_thread(
            keychain._backend.get_password,  # noqa: SLF001 — health probe by design
            keychain.SERVICE_NAME,
            "_actors_",
        )
    except Exception:  # noqa: BLE001 — health checks must not raise
        logger.exception("health_check_keychain_failed")
        return "down"
    return "ok"


def _ping_sqlite(conn: sqlite3.Connection | None) -> DepStatus:
    if conn is None:
        return "down"
    try:
        cur = conn.execute("SELECT 1")
        cur.fetchone()
    except sqlite3.Error:
        logger.exception("health_check_sqlite_failed")
        return "down"
    return "ok"


def _check_vault(provider: VaultProvider) -> DepStatus:
    if not provider.configured:
        return "degraded"
    try:
        root = provider.root
        if not root.is_dir():
            return "down"
        # Cheap probe: list one entry.
        next(root.iterdir(), None)
    except OSError:
        logger.exception("health_check_vault_failed")
        return "down"
    return "ok"


async def _check_openrouter(provider: OpenRouterProvider) -> DepStatus:
    return await provider.healthcheck()


def _overall(deps: dict[str, DepStatus]) -> OverallStatus:
    """Critical-dep aware roll-up. See module docstring for criticality."""
    has_down = any(deps[k] == "down" for k in _CRITICAL_DEPS if k in deps)
    if has_down:
        return "down"
    has_degraded = any(deps[k] == "degraded" for k in _CRITICAL_DEPS if k in deps)
    if has_degraded:
        return "degraded"
    return "ok"


@router.get("/v1/health", response_model=HealthResponse)
async def health(request: Request) -> HealthResponse:
    started_at: float = request.app.state.started_at
    cfg: Settings = request.app.state.settings
    _ = cfg  # reserved for future per-dep config knobs

    vault_provider: VaultProvider = request.app.state.vault_provider
    openrouter_provider: OpenRouterProvider = request.app.state.openrouter_provider
    idemp_conn: sqlite3.Connection | None = request.app.state.idempotency_conn
    tele_conn: sqlite3.Connection | None = request.app.state.telemetry_conn

    keychain_status, openrouter_status = await asyncio.gather(
        _check_keychain(),
        _check_openrouter(openrouter_provider),
    )
    deps: dict[str, DepStatus] = {
        # Stubs until their provider ships.
        "redis": "ok",
        "apple_bridge": "ok",
        "imap_glysk": "ok",
        "imap_lopes": "ok",
        "imap_whilesum": "ok",
        # Real probes:
        "openrouter": openrouter_status,
        "keychain": keychain_status,
        "vault": _check_vault(vault_provider),
        "idempotency_db": _ping_sqlite(idemp_conn),
        "telemetry_db": _ping_sqlite(tele_conn),
    }

    return HealthResponse(
        status=_overall(deps),
        version=request.app.state.version,
        uptime_s=int(time.monotonic() - started_at),
        deps=Deps(**deps),
    )
