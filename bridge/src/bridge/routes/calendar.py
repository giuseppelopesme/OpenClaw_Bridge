"""Calendar endpoints: list / create / update / delete events.

Schemas come straight from `docs/api-contract.md` (Calendar section). All
write operations are rate-limited under `apple:calendar:write` (default
300 req/min, burst 50 — the "everything else" bucket per the spec).

The provider is the module-level singleton on `app.state.calendar_provider`,
constructed at startup. No per-request state.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Path, Query, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from bridge.auth import AuthContext, require_scope
from bridge.providers.apple.calendar import CalendarProvider, Event
from bridge.ratelimit import require_rate

router = APIRouter(tags=["calendar"])


class _EventOut(BaseModel):
    id: str
    title: str
    start: str
    end: str
    calendar: str
    location: str | None = None
    notes: str | None = None


class CalendarListResponse(BaseModel):
    events: list[_EventOut]


class CalendarCreateRequest(BaseModel):
    calendar: str = Field(min_length=1)
    title: str = Field(min_length=1)
    start: str
    end: str
    location: str | None = None
    notes: str | None = None


class CalendarCreateResponse(BaseModel):
    id: str
    url: str


class CalendarUpdateRequest(BaseModel):
    title: str | None = None
    start: str | None = None
    end: str | None = None
    location: str | None = None
    notes: str | None = None


def _provider(request: Request) -> CalendarProvider:
    return request.app.state.calendar_provider  # type: ignore[no-any-return]


def _to_out(evt: Event) -> _EventOut:
    return _EventOut(
        id=evt.id,
        title=evt.title,
        start=evt.start,
        end=evt.end,
        calendar=evt.calendar,
        location=evt.location,
        notes=evt.notes,
    )


@router.get("/v1/calendar/events", response_model=CalendarListResponse)
async def list_events(
    request: Request,
    from_: Annotated[str, Query(alias="from", min_length=1)],
    to: Annotated[str, Query(min_length=1)],
    _auth: Annotated[AuthContext, Depends(require_scope("apple:calendar:read"))],
    calendar: Annotated[str | None, Query()] = None,
) -> CalendarListResponse:
    events = await _provider(request).list_events(from_, to, calendar=calendar)
    return CalendarListResponse(events=[_to_out(e) for e in events])


@router.post("/v1/calendar/events", status_code=201)
async def create_event(
    request: Request,
    body: CalendarCreateRequest,
    _auth: Annotated[AuthContext, Depends(require_scope("apple:calendar:write"))],
    _rate: Annotated[AuthContext, Depends(require_rate("apple:calendar:write"))],
) -> JSONResponse:
    new_id = await _provider(request).create_event(
        calendar=body.calendar,
        title=body.title,
        start=body.start,
        end=body.end,
        location=body.location,
        notes=body.notes,
    )
    payload = CalendarCreateResponse(id=new_id, url=f"calshow:{new_id}").model_dump()
    return JSONResponse(status_code=201, content=payload)


@router.patch("/v1/calendar/events/{event_id}")
async def update_event(
    request: Request,
    event_id: Annotated[str, Path(min_length=1)],
    body: CalendarUpdateRequest,
    _auth: Annotated[AuthContext, Depends(require_scope("apple:calendar:write"))],
    _rate: Annotated[AuthContext, Depends(require_rate("apple:calendar:write"))],
) -> dict[str, str]:
    await _provider(request).update_event(
        event_id,
        title=body.title,
        start=body.start,
        end=body.end,
        location=body.location,
        notes=body.notes,
    )
    return {"id": event_id, "status": "updated"}


@router.delete("/v1/calendar/events/{event_id}")
async def delete_event(
    request: Request,
    event_id: Annotated[str, Path(min_length=1)],
    _auth: Annotated[AuthContext, Depends(require_scope("apple:calendar:write"))],
    _rate: Annotated[AuthContext, Depends(require_rate("apple:calendar:write"))],
) -> dict[str, str]:
    await _provider(request).delete_event(event_id)
    return {"id": event_id, "status": "deleted"}
