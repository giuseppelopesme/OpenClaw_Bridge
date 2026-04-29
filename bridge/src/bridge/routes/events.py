"""Event bus endpoints — POST /v1/events/publish + GET /v1/events/subscribe.

The HTTP publish endpoint is gated by the standard auth + scope flow. The
WebSocket subscribe endpoint validates the bearer token *before* upgrading
the connection (so a 401 reaches a curl client, not a half-upgraded socket).

Both surfaces require Redis to be configured at app startup (Keychain
`provider.redis` seeded). Without it, the routes return 502
`dependency_unavailable` and the WebSocket closes with code 1011.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, Query, Request, WebSocket
from fastapi.websockets import WebSocketDisconnect
from pydantic import BaseModel, Field
from starlette.websockets import WebSocketState

from bridge.auth import AuthContext, TokenStore, require_scope
from bridge.errors import DependencyUnavailable
from bridge.eventbus import EventPublisher, EventSubscriber
from bridge.eventbus.subscriber import (
    validate_publish_topic,
    validate_subscribe_pattern,
)

logger = logging.getLogger("bridge.routes.events")

router = APIRouter(tags=["events"])

# WebSocket close codes — see RFC 6455 §7.4.
_WS_NORMAL: Literal[1000] = 1000
_WS_POLICY_VIOLATION: Literal[1008] = 1008
_WS_INTERNAL_ERROR: Literal[1011] = 1011


class EventPublishRequest(BaseModel):
    topic: str = Field(min_length=1, max_length=200)
    payload: dict[str, Any] = Field(default_factory=dict)
    ttl_s: int | None = None  # accepted, currently informational


class EventPublishResponse(BaseModel):
    event_id: str
    published_at: str


def _publisher(request: Request) -> EventPublisher:
    pub: EventPublisher | None = request.app.state.event_publisher
    if pub is None:
        raise DependencyUnavailable(
            "Event bus is not configured (Redis unavailable).",
            details={"missing": "redis"},
        )
    return pub


@router.post(
    "/v1/events/publish",
    response_model=EventPublishResponse,
    status_code=202,
)
async def events_publish(
    request: Request,
    body: EventPublishRequest,
    auth: Annotated[AuthContext, Depends(require_scope("events:publish"))],
) -> EventPublishResponse:
    validate_publish_topic(body.topic)
    pub = _publisher(request)
    result = await pub.publish(body.topic, body.payload, publisher=auth.actor)
    return EventPublishResponse(
        event_id=result.event_id,
        published_at=result.published_at,
    )


@router.websocket("/v1/events/subscribe")
async def events_subscribe(websocket: WebSocket, topic: str = Query(...)) -> None:
    """WebSocket: yield envelopes matching `topic` (with `*` wildcards).

    Auth happens BEFORE accept(); a missing or wrong-scope token gets a
    proper HTTP-style rejection. We do this manually because FastAPI's
    `Depends` on a WebSocket route runs after `accept()`.
    """
    actor, scopes = _websocket_auth(websocket)
    if actor is None:
        await websocket.close(code=_WS_POLICY_VIOLATION)
        return
    if "events:subscribe" not in scopes:
        await websocket.close(code=_WS_POLICY_VIOLATION)
        return

    try:
        validate_subscribe_pattern(topic)
    except Exception:  # noqa: BLE001 — translate to a close code below
        await websocket.close(code=_WS_POLICY_VIOLATION)
        return

    redis_client = websocket.app.state.redis_client
    if redis_client is None:
        await websocket.close(code=_WS_INTERNAL_ERROR)
        return

    await websocket.accept()
    logger.info(
        "ws_subscribe_open",
        extra={"actor": actor, "topic": topic},
    )
    try:
        async with EventSubscriber(redis_client, topic) as sub:
            forwarder = asyncio.create_task(_forward(websocket, sub))
            receiver = asyncio.create_task(_drain_client(websocket))
            done, pending = await asyncio.wait(
                {forwarder, receiver},
                return_when=asyncio.FIRST_COMPLETED,
            )
            for task in pending:
                task.cancel()
            for task in done:
                exc = task.exception()
                if exc is not None and not isinstance(exc, WebSocketDisconnect):
                    logger.warning(
                        "ws_subscribe_task_error",
                        extra={"actor": actor, "topic": topic, "exc": str(exc)},
                    )
    finally:
        if websocket.client_state != WebSocketState.DISCONNECTED:
            await websocket.close(code=_WS_NORMAL)
        logger.info(
            "ws_subscribe_close",
            extra={"actor": actor, "topic": topic},
        )


def _websocket_auth(websocket: WebSocket) -> tuple[str | None, frozenset[str]]:
    """Pre-handshake bearer-token validation. Returns (actor, scopes)."""
    header = websocket.headers.get("authorization", "")
    if not header.lower().startswith("bearer "):
        return None, frozenset()
    token = header[7:].strip()
    if not token:
        return None, frozenset()
    store: TokenStore = websocket.app.state.token_store
    record = store.lookup(token)
    if record is None:
        return None, frozenset()
    return record.actor, record.scopes


async def _forward(websocket: WebSocket, sub: EventSubscriber) -> None:
    """Pump decoded envelopes onto the websocket as JSON frames."""
    async for envelope in sub:
        if websocket.client_state == WebSocketState.DISCONNECTED:
            return
        await websocket.send_text(envelope.to_json())


async def _drain_client(websocket: WebSocket) -> None:
    """Detect client disconnect by attempting to receive. Returns when the
    client closes or sends anything (we treat any client message as a
    polite "stop")."""
    try:
        await websocket.receive_text()
    except WebSocketDisconnect:
        return
