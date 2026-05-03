"""Event-bus publish helper.

`POST /v1/events/publish` from a brain. Subscribing is `eventbus.py`;
this module is the publish counterpart.

The generated client's `EventPublishRequestPayload` is an attrs-based
"open" object (every field becomes an `additional_properties` entry).
We accept a plain `dict[str, Any]` and pack it for callers, so brains
write::

    from brains_shared.events import publish_event
    await publish_event(
        client,
        topic="agent.clu.draft.pending",
        payload={"draft_id": "...", "channel": "imessage", "preview": "..."},
    )
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from brains_shared._generated.api.events import (
    events_publish_v1_events_publish_post,
)
from brains_shared._generated.models.event_publish_request import (
    EventPublishRequest,
)
from brains_shared._generated.models.event_publish_request_payload import (
    EventPublishRequestPayload,
)
from brains_shared._generated.types import UNSET, Unset
from brains_shared.client import BridgeClient


@dataclass(frozen=True)
class PublishedEvent:
    """Bookkeeping returned by the bridge after a successful publish."""

    event_id: str
    published_at: str


class EventPublishError(RuntimeError):
    """Raised when the bridge returns a non-202 from `/v1/events/publish`."""

    def __init__(self, *, status: int, code: str, message: str) -> None:
        super().__init__(f"event publish failed: {status} {code}: {message}")
        self.status = status
        self.code = code
        self.message = message

    @classmethod
    def from_response(cls, status: int, content: bytes) -> EventPublishError:
        try:
            envelope = json.loads(content.decode("utf-8")).get("error", {})
        except (UnicodeDecodeError, json.JSONDecodeError, AttributeError):
            envelope = {}
        return cls(
            status=status,
            code=str(envelope.get("code", "unknown")),
            message=str(envelope.get("message", "")),
        )


async def publish_event(
    client: BridgeClient,
    *,
    topic: str,
    payload: dict[str, Any] | None = None,
    ttl_s: int | None = None,
) -> PublishedEvent:
    """Publish to the bridge's event bus. Returns the assigned `event_id`
    and `published_at` from the bridge's response."""
    body_payload: EventPublishRequestPayload | Unset = UNSET
    if payload is not None:
        body_payload = EventPublishRequestPayload.from_dict(payload)
    body = EventPublishRequest(
        topic=topic,
        payload=body_payload,
        ttl_s=ttl_s if ttl_s is not None else UNSET,
    )
    resp = await events_publish_v1_events_publish_post.asyncio_detailed(
        client=client.get_inner(),
        body=body,
    )
    if resp.status_code != 202:
        raise EventPublishError.from_response(int(resp.status_code), resp.content)
    parsed = json.loads(resp.content.decode("utf-8"))
    return PublishedEvent(
        event_id=str(parsed["event_id"]),
        published_at=str(parsed["published_at"]),
    )


__all__ = [
    "EventPublishError",
    "PublishedEvent",
    "publish_event",
]
