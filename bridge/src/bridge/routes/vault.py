"""Vault read/write endpoints.

`GET  /v1/vault/read?path=...`     scope: vault:read
`POST /v1/vault/write`             scope: vault:write  (idempotency + rate limiter)

Schemas come straight from `docs/api-contract.md`. The provider does the
filesystem work and path-safety enforcement; this module is wiring.

On a successful write we emit a structured log line at info level:

    {"event":"vault.changed","path":"...","op":"...","actor":"..."}

This is the placeholder for the real `vault.changed` Redis publish that lands
in step 4 of the build order.
"""

from __future__ import annotations

import logging
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from bridge.auth import AuthContext, require_scope
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
    # TODO(step 4): replace this log with a Redis publish to `vault.changed`.
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
