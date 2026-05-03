"""Agent draft helpers — thin wrappers over the generated client.

Brains call ``create_draft`` after running their LLM pass. Operators
(via the ``clu-drafts`` CLI) call ``list_drafts`` / ``get_draft`` /
``update_draft`` to inspect and approve.

The bridge owns the draft lifecycle (P1a). These helpers just package
the generated client's ``asyncio_detailed`` calls so callers get a
typed dataclass + clear error envelope handling.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Literal

from brains_shared._generated.api.agent import (
    create_draft_v1_agent_drafts_post,
    get_draft_v1_agent_drafts_draft_id_get,
    list_drafts_v1_agent_drafts_get,
    patch_draft_v1_agent_drafts_draft_id_patch,
)
from brains_shared._generated.models.draft_create_request import DraftCreateRequest
from brains_shared._generated.models.draft_create_request_agent import (
    DraftCreateRequestAgent,
)
from brains_shared._generated.models.draft_create_request_channel import (
    DraftCreateRequestChannel,
)
from brains_shared._generated.models.draft_patch_request import DraftPatchRequest
from brains_shared._generated.models.draft_patch_request_status_type_0 import (
    DraftPatchRequestStatusType0,
)
from brains_shared._generated.models.list_drafts_v1_agent_drafts_get_agent_type_0 import (
    ListDraftsV1AgentDraftsGetAgentType0,
)
from brains_shared._generated.models.list_drafts_v1_agent_drafts_get_status_type_0 import (
    ListDraftsV1AgentDraftsGetStatusType0,
)
from brains_shared._generated.types import UNSET
from brains_shared.client import BridgeClient

AgentName = Literal["clu", "tron", "flynn"]
ChannelName = Literal["imessage", "email"]
DraftStatus = Literal["pending", "approved", "rejected", "sent", "send_failed"]

_AGENT_MAP: dict[str, DraftCreateRequestAgent] = {
    "clu": DraftCreateRequestAgent.CLU,
    "tron": DraftCreateRequestAgent.TRON,
    "flynn": DraftCreateRequestAgent.FLYNN,
}
_CHANNEL_MAP: dict[str, DraftCreateRequestChannel] = {
    "imessage": DraftCreateRequestChannel.IMESSAGE,
    "email": DraftCreateRequestChannel.EMAIL,
}
_PATCH_STATUS_MAP: dict[str, DraftPatchRequestStatusType0] = {
    "pending": DraftPatchRequestStatusType0.PENDING,
    "approved": DraftPatchRequestStatusType0.APPROVED,
    "rejected": DraftPatchRequestStatusType0.REJECTED,
    "sent": DraftPatchRequestStatusType0.SENT,
    "send_failed": DraftPatchRequestStatusType0.SEND_FAILED,
}
_LIST_AGENT_MAP: dict[str, ListDraftsV1AgentDraftsGetAgentType0] = {
    "clu": ListDraftsV1AgentDraftsGetAgentType0.CLU,
    "tron": ListDraftsV1AgentDraftsGetAgentType0.TRON,
    "flynn": ListDraftsV1AgentDraftsGetAgentType0.FLYNN,
}
_LIST_STATUS_MAP: dict[str, ListDraftsV1AgentDraftsGetStatusType0] = {
    "pending": ListDraftsV1AgentDraftsGetStatusType0.PENDING,
    "approved": ListDraftsV1AgentDraftsGetStatusType0.APPROVED,
    "rejected": ListDraftsV1AgentDraftsGetStatusType0.REJECTED,
    "sent": ListDraftsV1AgentDraftsGetStatusType0.SENT,
    "send_failed": ListDraftsV1AgentDraftsGetStatusType0.SEND_FAILED,
}


@dataclass(frozen=True)
class Draft:
    """Mirrors the bridge's ``DraftOut`` over the wire."""

    draft_id: str
    agent: str
    channel: str
    to_handle: str
    body: str
    status: str
    created_at: str
    last_modified_at: str
    publisher: str
    in_reply_to_event_id: str | None = None
    preview: str | None = None
    approved_at: str | None = None
    approved_by: str | None = None
    reject_reason: str | None = None
    dispatch_message_id: str | None = None
    sent_at: str | None = None
    last_send_error_code: str | None = None
    last_send_error_message: str | None = None


@dataclass(frozen=True)
class CreatedDraft:
    """Returned by ``create_draft`` — minimal shape, no full body echo."""

    draft_id: str
    agent: str
    channel: str
    status: str
    created_at: str
    preview: str
    extra: dict[str, object] = field(default_factory=dict)


class AgentError(RuntimeError):
    """Raised when the bridge returns a non-success on an agent call."""

    def __init__(self, *, status: int, code: str, message: str) -> None:
        super().__init__(f"agent error {status} {code}: {message}")
        self.status = status
        self.code = code
        self.message = message

    @classmethod
    def from_response(cls, status: int, content: bytes) -> AgentError:
        try:
            envelope = json.loads(content.decode("utf-8")).get("error", {})
        except (UnicodeDecodeError, json.JSONDecodeError, AttributeError):
            envelope = {}
        return cls(
            status=status,
            code=str(envelope.get("code", "unknown")),
            message=str(envelope.get("message", "")),
        )


def _draft_from_dict(d: dict[str, object]) -> Draft:
    return Draft(
        draft_id=str(d["draft_id"]),
        agent=str(d["agent"]),
        channel=str(d["channel"]),
        to_handle=str(d["to_handle"]),
        body=str(d["body"]),
        status=str(d["status"]),
        created_at=str(d["created_at"]),
        last_modified_at=str(d["last_modified_at"]),
        publisher=str(d["publisher"]),
        in_reply_to_event_id=_str_or_none(d.get("in_reply_to_event_id")),
        preview=_str_or_none(d.get("preview")),
        approved_at=_str_or_none(d.get("approved_at")),
        approved_by=_str_or_none(d.get("approved_by")),
        reject_reason=_str_or_none(d.get("reject_reason")),
        dispatch_message_id=_str_or_none(d.get("dispatch_message_id")),
        sent_at=_str_or_none(d.get("sent_at")),
        last_send_error_code=_str_or_none(d.get("last_send_error_code")),
        last_send_error_message=_str_or_none(d.get("last_send_error_message")),
    )


def _str_or_none(value: object) -> str | None:
    return str(value) if value is not None else None


# -- public API ----------------------------------------------------------


async def create_draft(
    client: BridgeClient,
    *,
    agent: AgentName,
    to_handle: str,
    body: str,
    channel: ChannelName = "imessage",
    in_reply_to_event_id: str | None = None,
    preview: str | None = None,
) -> CreatedDraft:
    request_body = DraftCreateRequest(
        agent=_AGENT_MAP[agent],
        to_handle=to_handle,
        body=body,
        channel=_CHANNEL_MAP[channel],
        in_reply_to_event_id=in_reply_to_event_id if in_reply_to_event_id is not None else UNSET,
        preview=preview if preview is not None else UNSET,
    )
    resp = await create_draft_v1_agent_drafts_post.asyncio_detailed(
        client=client.get_inner(),
        body=request_body,
    )
    if resp.status_code != 201:
        raise AgentError.from_response(int(resp.status_code), resp.content)
    parsed = json.loads(resp.content.decode("utf-8"))
    return CreatedDraft(
        draft_id=str(parsed["draft_id"]),
        agent=str(parsed["agent"]),
        channel=str(parsed["channel"]),
        status=str(parsed["status"]),
        created_at=str(parsed["created_at"]),
        preview=str(parsed.get("preview", "")),
        extra={
            k: v
            for k, v in parsed.items()
            if k
            not in {
                "draft_id",
                "agent",
                "channel",
                "status",
                "created_at",
                "preview",
            }
        },
    )


async def list_drafts(
    client: BridgeClient,
    *,
    agent: AgentName | None = None,
    status: DraftStatus | None = None,
    limit: int = 50,
) -> list[Draft]:
    resp = await list_drafts_v1_agent_drafts_get.asyncio_detailed(
        client=client.get_inner(),
        agent=_LIST_AGENT_MAP[agent] if agent is not None else UNSET,
        status=_LIST_STATUS_MAP[status] if status is not None else UNSET,
        limit=limit,
    )
    if resp.status_code != 200:
        raise AgentError.from_response(int(resp.status_code), resp.content)
    parsed = json.loads(resp.content.decode("utf-8"))
    return [_draft_from_dict(d) for d in parsed.get("drafts", [])]


async def get_draft(client: BridgeClient, draft_id: str) -> Draft:
    resp = await get_draft_v1_agent_drafts_draft_id_get.asyncio_detailed(
        client=client.get_inner(),
        draft_id=draft_id,
    )
    if resp.status_code != 200:
        raise AgentError.from_response(int(resp.status_code), resp.content)
    return _draft_from_dict(json.loads(resp.content.decode("utf-8")))


async def update_draft(
    client: BridgeClient,
    draft_id: str,
    *,
    status: DraftStatus | None = None,
    body: str | None = None,
    reject_reason: str | None = None,
    approved_by: str | None = None,
) -> Draft:
    request_body = DraftPatchRequest(
        status=_PATCH_STATUS_MAP[status] if status is not None else UNSET,
        body=body if body is not None else UNSET,
        reject_reason=reject_reason if reject_reason is not None else UNSET,
        approved_by=approved_by if approved_by is not None else UNSET,
    )
    resp = await patch_draft_v1_agent_drafts_draft_id_patch.asyncio_detailed(
        client=client.get_inner(),
        draft_id=draft_id,
        body=request_body,
    )
    if resp.status_code != 200:
        raise AgentError.from_response(int(resp.status_code), resp.content)
    return _draft_from_dict(json.loads(resp.content.decode("utf-8")))


__all__ = [
    "AgentError",
    "AgentName",
    "ChannelName",
    "CreatedDraft",
    "Draft",
    "DraftStatus",
    "create_draft",
    "get_draft",
    "list_drafts",
    "update_draft",
]
