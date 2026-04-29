"""GET /v1/health — no auth.

Response shape comes verbatim from `docs/api-contract.md`. Dependency status is
stubbed to `"ok"` for every dep in step 1; real probes get wired in as each
provider lands.
"""

from __future__ import annotations

import time
from typing import Literal

from fastapi import APIRouter, Request
from pydantic import BaseModel

router = APIRouter(tags=["health"])

DepStatus = Literal["ok", "degraded", "down"]


class Deps(BaseModel):
    redis: DepStatus
    apple_bridge: DepStatus
    imap_glysk: DepStatus
    imap_lopes: DepStatus
    imap_whilesum: DepStatus
    openrouter: DepStatus


class HealthResponse(BaseModel):
    status: Literal["ok", "degraded", "down"]
    version: str
    uptime_s: int
    deps: Deps


@router.get("/v1/health", response_model=HealthResponse)
async def health(request: Request) -> HealthResponse:
    started_at: float = request.app.state.started_at
    return HealthResponse(
        status="ok",
        version=request.app.state.version,
        uptime_s=int(time.monotonic() - started_at),
        deps=Deps(
            redis="ok",
            apple_bridge="ok",
            imap_glysk="ok",
            imap_lopes="ok",
            imap_whilesum="ok",
            openrouter="ok",
        ),
    )
