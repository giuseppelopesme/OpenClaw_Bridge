"""GET /v1/auth/whoami — token introspection.

The first authenticated endpoint exists primarily to (a) give operators a way to
verify a token works and what scopes it carries, and (b) anchor the auth
middleware tests in step 1. It will keep its place once richer endpoints arrive.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from bridge.auth import AuthContext, require_auth

router = APIRouter(tags=["auth"])


class WhoamiResponse(BaseModel):
    actor: str
    scopes: list[str]


@router.get("/v1/auth/whoami", response_model=WhoamiResponse)
async def whoami(auth: Annotated[AuthContext, Depends(require_auth)]) -> WhoamiResponse:
    return WhoamiResponse(actor=auth.actor, scopes=sorted(auth.scopes))
