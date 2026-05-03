"""Contacts endpoint — read-only search.

`GET /v1/contacts/search?q=...&limit=10` — scope `apple:contacts:read`.

Returns minimal `{ name, phones[], emails[] }` records per the API contract.
No write operations in v1.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Query, Request
from pydantic import BaseModel

from bridge.auth import AuthContext, require_scope
from bridge.providers.apple.contacts import Contact, ContactsProvider

router = APIRouter(tags=["contacts"])


class _ContactOut(BaseModel):
    name: str
    phones: list[str]
    emails: list[str]


class ContactsSearchResponse(BaseModel):
    contacts: list[_ContactOut]


def _provider(request: Request) -> ContactsProvider:
    return request.app.state.contacts_provider  # type: ignore[no-any-return]


def _to_out(c: Contact) -> _ContactOut:
    return _ContactOut(name=c.name, phones=c.phones, emails=c.emails)


@router.get("/v1/contacts/search", response_model=ContactsSearchResponse)
async def search_contacts(
    request: Request,
    q: Annotated[str, Query(min_length=1)],
    _auth: Annotated[AuthContext, Depends(require_scope("apple:contacts:read"))],
    limit: Annotated[int, Query(ge=1, le=100)] = 10,
) -> ContactsSearchResponse:
    items = await _provider(request).search(q, limit=limit)
    return ContactsSearchResponse(contacts=[_to_out(c) for c in items])
