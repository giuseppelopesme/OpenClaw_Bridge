"""Vault read/write endpoints.

`GET  /v1/vault/read?path=...`     scope: vault:read
`POST /v1/vault/write`             scope: vault:write  (idempotency + rate limiter)

Schemas come straight from `docs/api-contract.md`. The provider does the
filesystem work and path-safety enforcement; this module is wiring.

On a successful write we publish to the `vault.changed` Redis topic (per
`docs/event-bus.md`) and additionally emit a structured log line for
local debugging. Publish failures do NOT fail the write — they're
swallowed with a warning, since the on-disk state is already mutated.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from bridge.auth import AuthContext, require_scope
from bridge.errors import DependencyUnavailable
from bridge.eventbus import EventPublisher
from bridge.providers.vault import VaultProvider, WriteMode
from bridge.ratelimit import require_rate

logger = logging.getLogger("bridge.vault")

router = APIRouter(tags=["vault"])


class VaultReadResponse(BaseModel):
    path: str
    content: str
    frontmatter: dict[str, Any]
    size: int
    modified_at: str


class VaultWriteRequest(BaseModel):
    path: str = Field(min_length=1)
    mode: Literal["create", "append", "replace"]
    content: str = ""
    frontmatter: dict[str, Any] | None = None


class VaultWriteResponse(BaseModel):
    path: str
    size: int
    written_at: str


def _provider(request: Request) -> VaultProvider:
    return request.app.state.vault_provider  # type: ignore[no-any-return]


@router.get("/v1/vault/read", response_model=VaultReadResponse)
async def vault_read(
    request: Request,
    path: Annotated[str, Query(min_length=1)],
    _auth: Annotated[AuthContext, Depends(require_scope("vault:read"))],
) -> VaultReadResponse:
    result = _provider(request).read(path)
    return VaultReadResponse(
        path=result.path,
        content=result.content,
        frontmatter=result.frontmatter,
        size=result.size,
        modified_at=result.modified_at,
    )


@router.post("/v1/vault/write")
async def vault_write(
    request: Request,
    body: VaultWriteRequest,
    auth: Annotated[AuthContext, Depends(require_scope("vault:write"))],
    _rate: Annotated[AuthContext, Depends(require_rate("vault:write"))],
) -> JSONResponse:
    result = _provider(request).write(
        body.path,
        mode=body.mode,
        content=body.content,
        frontmatter_data=body.frontmatter,
    )
    payload = VaultWriteResponse(
        path=result.path,
        size=result.size,
        written_at=result.written_at,
    ).model_dump()
    # Publish to the event bus. Failures are best-effort: the file is
    # already on disk, and a downstream subscriber missing one event is
    # an acceptable cost vs. failing a successful write. Subscribers
    # poll the bus and tolerate gaps; cf. docs/event-bus.md.
    publisher: EventPublisher | None = request.app.state.event_publisher
    if publisher is not None:
        try:
            await publisher.publish(
                "vault.changed",
                {
                    "path": result.path,
                    "op": result.op,
                    "changed_at": datetime.now(UTC).isoformat(),
                },
                publisher=auth.actor,
            )
        except DependencyUnavailable as exc:
            logger.warning(
                "vault_changed_publish_failed",
                extra={"path": result.path, "error": exc.message},
            )
    # Always emit the local log line — useful when Redis is degraded and
    # for grep-style debugging on a single host.
    logger.info(
        "vault.changed",
        extra={
            "event": "vault.changed",
            "path": result.path,
            "op": result.op,
            "actor": auth.actor,
        },
    )
    status = 201 if result.op == "create" else 200
    return JSONResponse(status_code=status, content=payload)


# Mode aliases re-exported so callers can import the same Literal as the provider.
_MODES: tuple[WriteMode, ...] = ("create", "append", "replace")
