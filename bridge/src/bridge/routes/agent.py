"""Agent endpoints — bridge-side draft store + approval flow (P1a).

The bridge owns the lifecycle of draft replies that brains generate.
Brains ``POST`` drafts here; operators ``GET``/``PATCH`` to inspect and
approve. On approval the bridge enqueues to the iMessage outbox (Session 7)
and correlates the relay's confirmation back to the draft row.

State machine::

    pending  --approve--> approved   --(relay /sent ok)-->    sent          (terminal-ok)
                                    --(relay /sent failed)-> send_failed   (retryable)
    pending  --reject--> rejected                                          (terminal-no)
    send_failed --approve--> approved (re-RPUSH the dispatch event)

The body of the dispatch RPUSH carries the freshly-allocated
``dispatch_message_id`` plus the same ``draft_id`` the operator approved,
so the existing ``POST /v1/imessage/sent`` handler in
``routes/imessage.py`` can look up the draft row and update
``sent_at`` / ``last_send_error_*``.

### Scopes

- ``agent:drafts:write``  — ``POST /v1/agent/drafts``     (CLU)
- ``agent:drafts:read``   — ``GET  /v1/agent/drafts*``    (operator CLI, future viewers)
- ``agent:drafts:approve``— ``PATCH /v1/agent/drafts/{id}`` (operator CLI)

### Idempotency

POST is wrapped by the idempotency middleware (Session 2). PATCH is not —
state-machine transitions are explicit and atomic via SQLite, so re-runs
are safe by virtue of the state check (a second ``approve`` against an
already-``approved`` row returns the current state without re-publishing).
"""

from __future__ import annotations

import json
import logging
import sqlite3
import uuid
from datetime import UTC, datetime
from typing import Annotated, Any, Final, Literal

from fastapi import APIRouter, Depends, Path, Query, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from redis.asyncio import Redis
from redis.exceptions import RedisError

from bridge.auth import AuthContext, require_scope
from bridge.errors import BadRequest, Conflict, DependencyUnavailable, NotFound
from bridge.eventbus import EventPublisher

logger = logging.getLogger("bridge.routes.agent")

router = APIRouter(tags=["agent"])

AgentName = Literal["clu", "tron", "flynn"]
ChannelName = Literal["imessage", "email"]
DraftStatus = Literal["pending", "approved", "rejected", "sent", "send_failed"]


# Allowed transitions. Map current_status -> set of acceptable target_status.
_ALLOWED_TRANSITIONS: Final[dict[str, frozenset[str]]] = {
    "pending": frozenset({"approved", "rejected"}),
    "approved": frozenset({"approved", "rejected"}),  # idempotent re-approve, allow late reject
    "send_failed": frozenset({"approved", "rejected"}),  # retry by re-approving
    "sent": frozenset(),  # terminal
    "rejected": frozenset(),  # terminal
}


# -- request / response models --------------------------------------------


class DraftCreateRequest(BaseModel):
    agent: AgentName
    channel: ChannelName = "imessage"
    to_handle: str = Field(min_length=1)
    body: str = Field(min_length=1)
    in_reply_to_event_id: str | None = None
    preview: str | None = None


class _DraftOut(BaseModel):
    draft_id: str
    agent: str
    channel: str
    to_handle: str
    body: str
    status: str
    created_at: str
    last_modified_at: str
    in_reply_to_event_id: str | None = None
    preview: str | None = None
    approved_at: str | None = None
    approved_by: str | None = None
    reject_reason: str | None = None
    dispatch_message_id: str | None = None
    sent_at: str | None = None
    last_send_error_code: str | None = None
    last_send_error_message: str | None = None
    publisher: str


class DraftListResponse(BaseModel):
    drafts: list[_DraftOut]


class DraftPatchRequest(BaseModel):
    status: DraftStatus | None = None
    body: str | None = None
    reject_reason: str | None = None
    approved_by: str | None = None


# -- helpers ---------------------------------------------------------------


def _now_iso() -> str:
    return datetime.now(UTC).isoformat()


def _conn(request: Request) -> sqlite3.Connection:
    conn: sqlite3.Connection | None = request.app.state.agent_conn
    if conn is None:
        raise DependencyUnavailable(
            "Agent draft store unavailable (agent.db).",
            details={"missing": "agent_db"},
        )
    return conn


def _redis(request: Request) -> Redis:
    client: Redis | None = request.app.state.redis_client
    if client is None:
        raise DependencyUnavailable(
            "Redis is not configured (outbound queue offline).",
            details={"missing": "redis"},
        )
    return client


def _publisher(request: Request) -> EventPublisher | None:
    return request.app.state.event_publisher  # type: ignore[no-any-return]


def _row_to_out(row: sqlite3.Row) -> _DraftOut:
    return _DraftOut(
        draft_id=str(row["draft_id"]),
        agent=str(row["agent"]),
        channel=str(row["channel"]),
        to_handle=str(row["to_handle"]),
        body=str(row["body"]),
        status=str(row["status"]),
        created_at=str(row["created_at"]),
        last_modified_at=str(row["last_modified_at"]),
        in_reply_to_event_id=row["in_reply_to_event_id"],
        preview=row["preview"],
        approved_at=row["approved_at"],
        approved_by=row["approved_by"],
        reject_reason=row["reject_reason"],
        dispatch_message_id=row["dispatch_message_id"],
        sent_at=row["sent_at"],
        last_send_error_code=row["last_send_error_code"],
        last_send_error_message=row["last_send_error_message"],
        publisher=str(row["publisher"]),
    )


# -- POST /v1/agent/drafts ------------------------------------------------


@router.post("/v1/agent/drafts", status_code=201)
async def create_draft(
    request: Request,
    body: DraftCreateRequest,
    auth: Annotated[AuthContext, Depends(require_scope("agent:drafts:write"))],
) -> JSONResponse:
    conn = _conn(request)
    draft_id = str(uuid.uuid4())
    now = _now_iso()
    preview = body.preview or body.body[:80]

    conn.execute(
        """
        INSERT INTO drafts (
            draft_id, agent, channel, to_handle, body, status,
            created_at, last_modified_at, in_reply_to_event_id, preview, publisher
        ) VALUES (?, ?, ?, ?, ?, 'pending', ?, ?, ?, ?, ?)
        """,
        (
            draft_id,
            body.agent,
            body.channel,
            body.to_handle,
            body.body,
            now,
            now,
            body.in_reply_to_event_id,
            preview,
            auth.actor,
        ),
    )

    # Publish agent.{agent}.draft.pending. Best-effort — the row is on disk.
    pub = _publisher(request)
    if pub is not None:
        try:
            await pub.publish(
                f"agent.{body.agent}.draft.pending",
                {
                    "draft_id": draft_id,
                    "channel": body.channel,
                    "preview": preview,
                },
                publisher=auth.actor,
            )
        except DependencyUnavailable as exc:
            logger.warning(
                "draft_pending_publish_failed",
                extra={"draft_id": draft_id, "error": exc.message},
            )

    payload = {
        "draft_id": draft_id,
        "agent": body.agent,
        "channel": body.channel,
        "status": "pending",
        "created_at": now,
        "preview": preview,
    }
    return JSONResponse(status_code=201, content=payload)


# -- GET /v1/agent/drafts -------------------------------------------------


@router.get("/v1/agent/drafts", response_model=DraftListResponse)
async def list_drafts(
    request: Request,
    _auth: Annotated[AuthContext, Depends(require_scope("agent:drafts:read"))],
    agent: Annotated[AgentName | None, Query()] = None,
    status: Annotated[DraftStatus | None, Query()] = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
) -> DraftListResponse:
    conn = _conn(request)
    conn.row_factory = sqlite3.Row
    where: list[str] = []
    params: list[Any] = []
    if agent is not None:
        where.append("agent = ?")
        params.append(agent)
    if status is not None:
        where.append("status = ?")
        params.append(status)
    where_clause = (" WHERE " + " AND ".join(where)) if where else ""
    params.append(limit)
    # `where_clause` is built from a fixed set of column-name fragments,
    # never from user input — params are bound positionally.
    cur = conn.execute(
        f"SELECT * FROM drafts{where_clause} ORDER BY created_at DESC LIMIT ?",  # noqa: S608
        params,
    )
    rows = cur.fetchall()
    return DraftListResponse(drafts=[_row_to_out(r) for r in rows])


# -- GET /v1/agent/drafts/{draft_id} -------------------------------------


@router.get("/v1/agent/drafts/{draft_id}", response_model=_DraftOut)
async def get_draft(
    request: Request,
    draft_id: Annotated[str, Path(min_length=1)],
    _auth: Annotated[AuthContext, Depends(require_scope("agent:drafts:read"))],
) -> _DraftOut:
    conn = _conn(request)
    conn.row_factory = sqlite3.Row
    row = conn.execute(
        "SELECT * FROM drafts WHERE draft_id = ?",
        (draft_id,),
    ).fetchone()
    if row is None:
        raise NotFound(f"Draft not found: {draft_id}", details={"draft_id": draft_id})
    return _row_to_out(row)


# -- PATCH /v1/agent/drafts/{draft_id} -----------------------------------


@router.patch("/v1/agent/drafts/{draft_id}", response_model=_DraftOut)
async def patch_draft(
    request: Request,
    draft_id: Annotated[str, Path(min_length=1)],
    body: DraftPatchRequest,
    auth: Annotated[AuthContext, Depends(require_scope("agent:drafts:approve"))],
) -> _DraftOut:
    conn = _conn(request)
    conn.row_factory = sqlite3.Row

    if body.status is None and body.body is None:
        raise BadRequest(
            "PATCH requires at least one of: status, body.",
            details={"draft_id": draft_id},
        )

    # Atomic read + transition + write.
    with conn:
        cur = conn.execute(
            "SELECT * FROM drafts WHERE draft_id = ?",
            (draft_id,),
        )
        row = cur.fetchone()
        if row is None:
            raise NotFound(f"Draft not found: {draft_id}", details={"draft_id": draft_id})

        current_status = str(row["status"])
        target_status = body.status or current_status

        if target_status != current_status:
            allowed = _ALLOWED_TRANSITIONS.get(current_status, frozenset())
            if target_status not in allowed:
                raise Conflict(
                    f"Illegal status transition {current_status!r} -> {target_status!r}.",
                    details={
                        "draft_id": draft_id,
                        "current": current_status,
                        "requested": target_status,
                        "allowed": sorted(allowed),
                    },
                )

        # Body edits are only allowed before terminal/sent states.
        if body.body is not None and current_status in ("sent", "rejected"):
            raise Conflict(
                f"Cannot edit body in terminal state {current_status!r}.",
                details={"draft_id": draft_id, "current": current_status},
            )

        # Build the UPDATE.
        sets: list[str] = ["last_modified_at = ?"]
        params: list[Any] = [_now_iso()]

        new_body = body.body if body.body is not None else str(row["body"])
        if body.body is not None:
            sets.append("body = ?")
            params.append(body.body)

        new_status = target_status
        sets.append("status = ?")
        params.append(new_status)

        new_dispatch_message_id = row["dispatch_message_id"]

        if new_status == "approved" and current_status in ("pending", "send_failed", "approved"):
            new_dispatch_message_id = str(uuid.uuid4())
            sets.append("dispatch_message_id = ?")
            params.append(new_dispatch_message_id)
            sets.append("approved_at = ?")
            params.append(_now_iso())
            if body.approved_by is not None:
                sets.append("approved_by = ?")
                params.append(body.approved_by)
            elif row["approved_by"] is None:
                sets.append("approved_by = ?")
                params.append(auth.actor)
            # Clear any stale failure marker on retry.
            sets.append("last_send_error_code = NULL")
            sets.append("last_send_error_message = NULL")

        if new_status == "rejected" and body.reject_reason is not None:
            sets.append("reject_reason = ?")
            params.append(body.reject_reason)

        params.append(draft_id)
        # `sets` is built from a fixed catalogue of column-assignment
        # fragments; values are bound positionally via `params`.
        conn.execute(
            f"UPDATE drafts SET {', '.join(sets)} WHERE draft_id = ?",  # noqa: S608
            params,
        )

        updated = conn.execute(
            "SELECT * FROM drafts WHERE draft_id = ?",
            (draft_id,),
        ).fetchone()

    # Side effects (after the txn commits) — outside the `with conn` block.
    if new_status == "approved" and (
        current_status in ("pending", "send_failed")
        or (current_status == "approved" and target_status == "approved")
    ):
        await _enqueue_dispatch(
            request,
            draft_id=draft_id,
            agent=str(updated["agent"]),
            to_handle=str(updated["to_handle"]),
            body=new_body,
            channel=str(updated["channel"]),
            dispatch_message_id=str(new_dispatch_message_id),
            publisher=auth.actor,
        )
        await _publish_approved(
            request,
            agent=str(updated["agent"]),
            draft_id=draft_id,
            approved_by=str(updated["approved_by"] or auth.actor),
            approved_at=str(updated["approved_at"]),
            publisher=auth.actor,
        )

    return _row_to_out(updated)


# -- dispatch + event helpers --------------------------------------------


async def _enqueue_dispatch(
    request: Request,
    *,
    draft_id: str,
    agent: str,
    to_handle: str,
    body: str,
    channel: str,
    dispatch_message_id: str,
    publisher: str,
) -> None:
    if channel != "imessage":
        # v1 only dispatches imessage; other channels would have their own
        # outbound queue. Surface as 502 so the operator knows.
        raise DependencyUnavailable(
            f"Channel {channel!r} dispatch not implemented in v1.",
            details={"draft_id": draft_id, "channel": channel},
        )
    redis_client = _redis(request)
    job: dict[str, Any] = {
        "message_id": dispatch_message_id,
        "from": agent,
        "to": to_handle,
        "body": body,
        "service": "iMessage",
        "queued_at": _now_iso(),
        "request_id": getattr(request.state, "request_id", "") or "",
        "publisher": publisher,
        "draft_id": draft_id,
    }
    queue_key = f"imessage:outbound:{agent}"
    try:
        # redis-py async-client returns Awaitable from the union with sync.
        await redis_client.rpush(queue_key, json.dumps(job))  # type: ignore[misc]
    except RedisError as exc:
        raise DependencyUnavailable(
            "Failed to enqueue draft dispatch.",
            details={"draft_id": draft_id, "error": str(exc)},
        ) from exc


async def _publish_approved(
    request: Request,
    *,
    agent: str,
    draft_id: str,
    approved_by: str,
    approved_at: str,
    publisher: str,
) -> None:
    pub = _publisher(request)
    if pub is None:
        return
    try:
        await pub.publish(
            f"agent.{agent}.draft.approved",
            {
                "draft_id": draft_id,
                "approved_by": approved_by,
                "approved_at": approved_at,
            },
            publisher=publisher,
        )
    except DependencyUnavailable as exc:
        logger.warning(
            "draft_approved_publish_failed",
            extra={"draft_id": draft_id, "error": exc.message},
        )


# -- correlation hook (called from routes/imessage.py) -------------------


def correlate_send_outcome(
    conn: sqlite3.Connection,
    *,
    dispatch_message_id: str,
    status: str,
    sent_at: str | None,
    error_code: str | None,
    error_message: str | None,
) -> str | None:
    """Correlate an iMessage `/v1/imessage/sent` POST back to a draft row.

    Returns the draft_id if a row was updated, else None. Called by the
    iMessage route's `/v1/imessage/sent` handler after it publishes its
    own `imessage.sent.{agent}` / `imessage.send.failed.{agent}` event.

    On `status == "success"`: marks the draft `sent` with `sent_at`.
    On `status == "failed"`: marks the draft `send_failed` and stores the
    error so the CLI can `retry`.
    """
    conn.row_factory = sqlite3.Row
    with conn:
        row = conn.execute(
            "SELECT draft_id FROM drafts WHERE dispatch_message_id = ?",
            (dispatch_message_id,),
        ).fetchone()
        if row is None:
            return None
        draft_id = str(row["draft_id"])
        now = _now_iso()
        if status == "success":
            conn.execute(
                "UPDATE drafts SET status = 'sent', sent_at = ?, last_modified_at = ?, "
                "last_send_error_code = NULL, last_send_error_message = NULL "
                "WHERE draft_id = ?",
                (sent_at or now, now, draft_id),
            )
        else:
            conn.execute(
                "UPDATE drafts SET status = 'send_failed', "
                "last_send_error_code = ?, last_send_error_message = ?, "
                "last_modified_at = ? WHERE draft_id = ?",
                (error_code or "unknown", error_message or "", now, draft_id),
            )
    return draft_id
