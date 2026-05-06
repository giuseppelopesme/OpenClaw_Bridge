"""iMessage endpoints — send / inbound / outbox / sent.

`POST /v1/imessage/send`     scope `imessage:send`   (rate-limited 30/min, burst 5)
`POST /v1/imessage/inbound`  scope `imessage:relay`
`GET  /v1/imessage/outbox`   scope `imessage:relay`  (long-poll BLPOP)
`POST /v1/imessage/sent`     scope `imessage:relay`

The relay process holds `imessage:relay` and uses it to: pull queued
outbound jobs from the bridge (long-poll), report inbound chat.db
observations, and confirm dispatch outcomes. Brains hold `imessage:send`
to enqueue outbound messages.

### Outbound queue (Redis list)

`POST /v1/imessage/send` → `RPUSH imessage:outbound:{from}` with a JSON
job blob. `GET /v1/imessage/outbox?agent={agent}` → `BLPOP
imessage:outbound:{agent}` with a 25s default timeout. Durable across
relay restarts; events lost only if Redis itself is unavailable.

### Outcome events

After dispatch, the relay POSTs `/v1/imessage/sent` with `status`
"success" or "failed". The bridge translates that into one of two topics
per `docs/event-bus.md`:

- success → `imessage.sent.{agent}` with `{message_id, to, body, sent_at}`
- failed  → `imessage.send.failed.{agent}` with
            `{message_id, to, body, error_code, error_message, attempted_at}`

Inbound chat.db observations (`POST /v1/imessage/inbound`) publish
`imessage.received.{agent}` with `{from, body, chat_guid, received_at}`.
"""

from __future__ import annotations

import json
import logging
import uuid
from datetime import UTC, datetime
from typing import Annotated, Any, Final, Literal

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel, Field
from redis.asyncio import Redis
from redis.exceptions import RedisError

from bridge.auth import AuthContext, require_scope
from bridge.errors import DependencyUnavailable
from bridge.eventbus import EventPublisher
from bridge.ratelimit import require_rate

logger = logging.getLogger("bridge.routes.imessage")

router = APIRouter(tags=["imessage"])

# Agent identity — well-formed lowercase identifier (1–32 chars, leading
# letter, alphanumerics/underscore). The bridge accepts any name; the
# operator's deployment chooses one and threads it through topic names,
# Keychain actor keys, and the brain's runtime config.
_AGENT_NAME_PATTERN = r"^[a-z][a-z0-9_]{0,31}$"
# `main` is the special sender meaning "the operator themselves"; any
# other sender must look like a valid agent name.
_SENDER_NAME_PATTERN = r"^(main|[a-z][a-z0-9_]{0,31})$"
AgentName = Annotated[str, Field(pattern=_AGENT_NAME_PATTERN)]
SenderName = Annotated[str, Field(pattern=_SENDER_NAME_PATTERN)]
ServiceKind = Literal["iMessage", "SMS"]
SendStatus = Literal["success", "failed"]

# Default BLPOP timeout for the outbox endpoint. Cap is enforced server-side
# so a misbehaving client cannot pin a worker thread for hours.
_DEFAULT_BLPOP_S: Final[int] = 25
_MAX_BLPOP_S: Final[int] = 60


def _queue_key(agent: str) -> str:
    return f"imessage:outbound:{agent}"


# -- request / response models ---------------------------------------------


class IMessageSendRequest(BaseModel):
    sender: str = Field(
        alias="from",
        serialization_alias="from",
        pattern=_SENDER_NAME_PATTERN,
    )
    to: str = Field(min_length=1)
    body: str = Field(min_length=1)
    service: ServiceKind = "iMessage"

    model_config = {"populate_by_name": True}


class IMessageSendResponse(BaseModel):
    message_id: str
    queued_at: str


class IMessageInboundRequest(BaseModel):
    agent: AgentName
    sender: str = Field(alias="from", serialization_alias="from", min_length=1)
    body: str = Field(min_length=1)
    received_at: str = Field(min_length=1)
    chat_guid: str = Field(min_length=1)

    model_config = {"populate_by_name": True}


class IMessageInboundResponse(BaseModel):
    received: bool
    event_id: str


class IMessageSentRequest(BaseModel):
    agent: AgentName
    message_id: str = Field(min_length=1)
    to: str = Field(min_length=1)
    body: str = Field(min_length=1)
    status: SendStatus
    sent_at: str | None = None
    error_code: str | None = None
    error_message: str | None = None


class IMessageSentResponse(BaseModel):
    acknowledged: bool
    event_id: str


# -- helpers ---------------------------------------------------------------


def _redis(request: Request) -> Redis:
    client: Redis | None = request.app.state.redis_client
    if client is None:
        raise DependencyUnavailable(
            "Redis is not configured (event bus + outbound queue offline).",
            details={"missing": "redis"},
        )
    return client


def _publisher(request: Request) -> EventPublisher:
    pub: EventPublisher | None = request.app.state.event_publisher
    if pub is None:
        raise DependencyUnavailable(
            "Event publisher unavailable (Redis offline).",
            details={"missing": "redis"},
        )
    return pub


# -- endpoints -------------------------------------------------------------


@router.post("/v1/imessage/send", status_code=202)
async def imessage_send(
    request: Request,
    body: IMessageSendRequest,
    auth: Annotated[AuthContext, Depends(require_scope("imessage:send"))],
    _rate: Annotated[AuthContext, Depends(require_rate("imessage:send"))],
) -> JSONResponse:
    redis_client = _redis(request)
    request_id = getattr(request.state, "request_id", "") or ""
    message_id = str(uuid.uuid4())
    queued_at = datetime.now(UTC).isoformat()
    job: dict[str, Any] = {
        "message_id": message_id,
        "from": body.sender,
        "to": body.to,
        "body": body.body,
        "service": body.service,
        "queued_at": queued_at,
        "request_id": request_id,
        "publisher": auth.actor,
    }
    try:
        # redis-py types its async surface as `Awaitable[X] | X`. The async
        # client always returns an awaitable; the union is for the sync sibling.
        await redis_client.rpush(_queue_key(body.sender), json.dumps(job))  # type: ignore[misc]
    except RedisError as exc:
        raise DependencyUnavailable(
            "Failed to enqueue iMessage job.",
            details={"agent": body.sender, "error": str(exc)},
        ) from exc
    payload = IMessageSendResponse(message_id=message_id, queued_at=queued_at).model_dump()
    return JSONResponse(status_code=202, content=payload)


@router.post("/v1/imessage/inbound", response_model=IMessageInboundResponse)
async def imessage_inbound(
    request: Request,
    body: IMessageInboundRequest,
    auth: Annotated[AuthContext, Depends(require_scope("imessage:relay"))],
) -> IMessageInboundResponse:
    publisher = _publisher(request)
    topic = f"imessage.received.{body.agent}"
    payload = {
        "from": body.sender,
        "body": body.body,
        "received_at": body.received_at,
        "chat_guid": body.chat_guid,
    }
    result = await publisher.publish(topic, payload, publisher=auth.actor)
    return IMessageInboundResponse(received=True, event_id=result.event_id)


@router.get("/v1/imessage/outbox")
async def imessage_outbox(
    request: Request,
    agent: Annotated[AgentName, Query()],
    _auth: Annotated[AuthContext, Depends(require_scope("imessage:relay"))],
    timeout_s: Annotated[int, Query(ge=0, le=_MAX_BLPOP_S)] = _DEFAULT_BLPOP_S,
) -> Response:
    redis_client = _redis(request)
    try:
        # redis-py async-client returns Awaitable[list[bytes]]; stubs OR it with
        # the sync return type which mypy can't reconcile.
        result = await redis_client.blpop(  # type: ignore[misc]
            [_queue_key(agent)],
            timeout=timeout_s,
        )
    except RedisError as exc:
        raise DependencyUnavailable(
            "Failed to dequeue iMessage job.",
            details={"agent": agent, "error": str(exc)},
        ) from exc
    if result is None:
        # No job within the long-poll budget. 204 means "try again".
        return Response(status_code=204)
    _, raw_job = result
    try:
        job = json.loads(raw_job.decode("utf-8") if isinstance(raw_job, bytes) else raw_job)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        # Corrupted entry — drop it, log loudly, return 204 so the relay
        # comes back. We do NOT re-queue.
        logger.warning(
            "imessage_outbox_corrupt_entry",
            extra={"agent": agent, "error": str(exc)},
        )
        return Response(status_code=204)
    return JSONResponse(status_code=200, content=job)


@router.post("/v1/imessage/sent", response_model=IMessageSentResponse)
async def imessage_sent(
    request: Request,
    body: IMessageSentRequest,
    auth: Annotated[AuthContext, Depends(require_scope("imessage:relay"))],
) -> IMessageSentResponse:
    publisher = _publisher(request)
    if body.status == "success":
        topic = f"imessage.sent.{body.agent}"
        sent_at = body.sent_at or datetime.now(UTC).isoformat()
        payload: dict[str, Any] = {
            "message_id": body.message_id,
            "to": body.to,
            "body": body.body,
            "sent_at": sent_at,
        }
    else:
        topic = f"imessage.send.failed.{body.agent}"
        sent_at = body.sent_at or datetime.now(UTC).isoformat()
        payload = {
            "message_id": body.message_id,
            "to": body.to,
            "body": body.body,
            "error_code": body.error_code or "unknown",
            "error_message": body.error_message or "",
            "attempted_at": sent_at,
        }
    result = await publisher.publish(topic, payload, publisher=auth.actor)

    # Correlate back to the agent draft (if any) — this dispatch may have
    # come from PATCH /v1/agent/drafts/{id} and the draft row is waiting
    # for sent_at / last_send_error_*. Best-effort; correlation failure
    # does not fail the relay's POST.
    agent_conn = request.app.state.agent_conn
    if agent_conn is not None:
        # Imported here (rather than at module top) to keep the
        # imessage route's import surface narrow and to avoid any
        # circular-import surprise.
        from bridge.routes.agent import correlate_send_outcome  # noqa: PLC0415

        try:
            draft_id = correlate_send_outcome(
                agent_conn,
                dispatch_message_id=body.message_id,
                status=body.status,
                sent_at=sent_at if body.status == "success" else None,
                error_code=body.error_code,
                error_message=body.error_message,
            )
            if draft_id is not None:
                logger.info(
                    "imessage_sent_correlated_to_draft",
                    extra={
                        "draft_id": draft_id,
                        "message_id": body.message_id,
                        "status": body.status,
                    },
                )
        except Exception:  # noqa: BLE001 — correlation must not break the route
            logger.exception(
                "imessage_sent_correlation_failed",
                extra={"message_id": body.message_id},
            )

    return IMessageSentResponse(acknowledged=True, event_id=result.event_id)
