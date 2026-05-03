"""Reminders endpoints — list / create / update / delete.

Schemas mirror EventKit's reminder shape per `docs/api-contract.md`.
Writes are rate-limited under `apple:reminders:write` (default
"everything else" bucket — 300 req/min, burst 50).
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Path, Query, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from bridge.auth import AuthContext, require_scope
from bridge.providers.apple.reminders import Reminder, RemindersProvider
from bridge.ratelimit import require_rate

router = APIRouter(tags=["reminders"])


class _ReminderOut(BaseModel):
    id: str
    title: str
    list: str
    completed: bool
    due_date: str | None = None
    notes: str | None = None


class RemindersListResponse(BaseModel):
    reminders: list[_ReminderOut]


class RemindersCreateRequest(BaseModel):
    list: str = Field(min_length=1)
    title: str = Field(min_length=1)
    due_date: str | None = None
    notes: str | None = None


class RemindersCreateResponse(BaseModel):
    id: str


class RemindersUpdateRequest(BaseModel):
    title: str | None = None
    notes: str | None = None
    due_date: str | None = None
    completed: bool | None = None


def _provider(request: Request) -> RemindersProvider:
    return request.app.state.reminders_provider  # type: ignore[no-any-return]


def _to_out(r: Reminder) -> _ReminderOut:
    return _ReminderOut(
        id=r.id,
        title=r.title,
        list=r.list,
        completed=r.completed,
        due_date=r.due_date,
        notes=r.notes,
    )


@router.get("/v1/reminders", response_model=RemindersListResponse)
async def list_reminders(
    request: Request,
    _auth: Annotated[AuthContext, Depends(require_scope("apple:reminders:read"))],
    list_: Annotated[str | None, Query(alias="list")] = None,
    completed: Annotated[bool, Query()] = False,
) -> RemindersListResponse:
    items = await _provider(request).list_reminders(list_, completed=completed)
    return RemindersListResponse(reminders=[_to_out(r) for r in items])


@router.post("/v1/reminders", status_code=201)
async def create_reminder(
    request: Request,
    body: RemindersCreateRequest,
    _auth: Annotated[AuthContext, Depends(require_scope("apple:reminders:write"))],
    _rate: Annotated[AuthContext, Depends(require_rate("apple:reminders:write"))],
) -> JSONResponse:
    new_id = await _provider(request).create_reminder(
        body.list,
        body.title,
        due_date=body.due_date,
        notes=body.notes,
    )
    payload = RemindersCreateResponse(id=new_id).model_dump()
    return JSONResponse(status_code=201, content=payload)


@router.patch("/v1/reminders/{reminder_id}")
async def update_reminder(
    request: Request,
    reminder_id: Annotated[str, Path(min_length=1)],
    body: RemindersUpdateRequest,
    _auth: Annotated[AuthContext, Depends(require_scope("apple:reminders:write"))],
    _rate: Annotated[AuthContext, Depends(require_rate("apple:reminders:write"))],
) -> dict[str, str]:
    await _provider(request).update_reminder(
        reminder_id,
        title=body.title,
        notes=body.notes,
        due_date=body.due_date,
        completed=body.completed,
    )
    return {"id": reminder_id, "status": "updated"}


@router.delete("/v1/reminders/{reminder_id}")
async def delete_reminder(
    request: Request,
    reminder_id: Annotated[str, Path(min_length=1)],
    _auth: Annotated[AuthContext, Depends(require_scope("apple:reminders:write"))],
    _rate: Annotated[AuthContext, Depends(require_rate("apple:reminders:write"))],
) -> dict[str, str]:
    await _provider(request).delete_reminder(reminder_id)
    return {"id": reminder_id, "status": "deleted"}
