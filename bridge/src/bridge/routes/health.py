"""GET /v1/health — no auth.

Response shape from `docs/api-contract.md`. Real per-dep probes landed in
Sessions 3 + 4 + 5 + 6. All deps are now live probes — no stubs left.

Criticality:
- Critical (a "down" or "degraded" pushes overall status off "ok"):
  `keychain`, `idempotency_db`, `telemetry_db`, `vault`, `redis`,
  `apple_bridge`.
- Non-critical: `openrouter`, `imap_*`. The LLM endpoint owns its own
  errors; a slow OpenRouter shouldn't flap health. The three IMAP
  accounts are convenience surfaces — if one's mail server is down,
  email reads fail loudly via the route's 502, but the bridge stays
  serving the rest. Operators see the gap in the deps map.

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
from bridge.errors import DependencyUnavailable
from bridge.eventbus import EventPublisher
from bridge.providers.apple.runner import run_osascript
from bridge.providers.email.imap import IMAPProvider
from bridge.providers.llm.openrouter import OpenRouterProvider
from bridge.providers.vault import VaultProvider

logger = logging.getLogger("bridge.health")

router = APIRouter(tags=["health"])

DepStatus = Literal["ok", "degraded", "down"]
OverallStatus = Literal["ok", "degraded", "down"]

_CRITICAL_DEPS: Final[frozenset[str]] = frozenset(
    {
        "keychain",
        "idempotency_db",
        "telemetry_db",
        "agent_db",
        "vault",
        "redis",
        "apple_bridge",
    },
)


_IMAP_ACCOUNTS: Final[tuple[str, ...]] = ("glysk", "lopes", "whilesum")


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
    agent_db: DepStatus


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


async def _check_redis(publisher: EventPublisher | None) -> DepStatus:
    if publisher is None:
        return "down"
    return await publisher.healthcheck()


async def _check_imap(provider: IMAPProvider | None) -> DepStatus:
    """No provider for this account → 'down' (config or password missing)."""
    if provider is None:
        return "down"
    try:
        return await provider.healthcheck()
    except Exception:  # noqa: BLE001 — health checks must not raise
        logger.exception("health_check_imap_failed")
        return "down"


async def _check_apple_bridge() -> DepStatus:
    """Cheap inert osascript probe.

    Runs `tell application "System Events" to return true`. A successful
    "true" means osascript is available and at least one app is reachable.
    Timeouts and runner errors collapse to "down" — TCC denials surface
    as runner errors and are also reported "down".
    """
    try:
        out = await run_osascript(
            'tell application "System Events" to return true',
            timeout_s=2.0,
        )
    except DependencyUnavailable:
        return "down"
    return "ok" if out == "true" else "down"


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
    event_publisher: EventPublisher | None = request.app.state.event_publisher
    idemp_conn: sqlite3.Connection | None = request.app.state.idempotency_conn
    tele_conn: sqlite3.Connection | None = request.app.state.telemetry_conn
    agent_conn: sqlite3.Connection | None = request.app.state.agent_conn

    imap_providers: dict[str, IMAPProvider] = request.app.state.email_imap_providers

    results = await asyncio.gather(
        _check_keychain(),
        _check_openrouter(openrouter_provider),
        _check_redis(event_publisher),
        _check_apple_bridge(),
        *(_check_imap(imap_providers.get(name)) for name in _IMAP_ACCOUNTS),
    )
    keychain_status, openrouter_status, redis_status, apple_status = results[:4]
    imap_statuses = dict(zip(_IMAP_ACCOUNTS, results[4:], strict=True))
    deps: dict[str, DepStatus] = {
        "apple_bridge": apple_status,
        "redis": redis_status,
        "openrouter": openrouter_status,
        "keychain": keychain_status,
        "vault": _check_vault(vault_provider),
        "idempotency_db": _ping_sqlite(idemp_conn),
        "telemetry_db": _ping_sqlite(tele_conn),
        "agent_db": _ping_sqlite(agent_conn),
        "imap_glysk": imap_statuses["glysk"],
        "imap_lopes": imap_statuses["lopes"],
        "imap_whilesum": imap_statuses["whilesum"],
    }

    return HealthResponse(
        status=_overall(deps),
        version=request.app.state.version,
        uptime_s=int(time.monotonic() - started_at),
        deps=Deps(**deps),
    )
