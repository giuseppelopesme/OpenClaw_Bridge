"""iMessage SDK helper — `send` for direct outbound messages.

Most outbound iMessages flow through the bridge's draft-approval
pipeline: the draft is approved via PATCH /v1/agent/drafts/{id}, the
bridge enqueues to the relay's outbox itself, no direct caller.

This helper exists for callers that need a *direct* send without the
human-approval loop — e.g. a future scheduled-reminders dispatcher, or
an admin tool. The default brain does not use this; it only creates
drafts via ``brains_shared.agent.create_draft``.

If you find yourself reaching for this in a brain handler, stop —
that's an end-run around the approval gate.

Sender identity: any well-formed agent identifier (``[a-z][a-z0-9_]*``,
1–32 chars), or the special string ``"main"`` to send as the operator.
The bridge enforces the same regex.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Literal

from brains_shared._generated.api.imessage import imessage_send_v1_imessage_send_post
from brains_shared._generated.models.i_message_send_request import IMessageSendRequest
from brains_shared._generated.models.i_message_send_request_service import (
    IMessageSendRequestService,
)
from brains_shared.client import BridgeClient, idempotency_key

ServiceKind = Literal["iMessage", "SMS"]

_SERVICE_MAP: dict[str, IMessageSendRequestService] = {
    "iMessage": IMessageSendRequestService.IMESSAGE,
    "SMS": IMessageSendRequestService.SMS,
}


@dataclass(frozen=True)
class SendResult:
    """The bridge's `202` shape from `POST /v1/imessage/send`."""

    message_id: str
    queued_at: str


class SendError(RuntimeError):
    """Raised when the bridge returns a non-202 from `POST /v1/imessage/send`."""

    def __init__(self, *, status: int, code: str, message: str) -> None:
        super().__init__(f"imessage send failed: {status} {code}: {message}")
        self.status = status
        self.code = code
        self.message = message

    @classmethod
    def from_response(cls, status: int, content: bytes) -> SendError:
        try:
            envelope = json.loads(content.decode("utf-8")).get("error", {})
        except (UnicodeDecodeError, json.JSONDecodeError, AttributeError):
            envelope = {}
        return cls(
            status=status,
            code=str(envelope.get("code", "unknown")),
            message=str(envelope.get("message", "")),
        )


async def send(
    client: BridgeClient,
    *,
    sender: str,
    to: str,
    body: str,
    service: ServiceKind = "iMessage",
    idempotency_key_value: str | None = None,
) -> SendResult:
    """Direct outbound iMessage. See module docstring for usage notes."""
    request_body = IMessageSendRequest(
        from_=sender,
        to=to,
        body=body,
        service=_SERVICE_MAP[service],
    )

    if idempotency_key_value is not None:
        with idempotency_key(idempotency_key_value):
            resp = await imessage_send_v1_imessage_send_post.asyncio_detailed(
                client=client.get_inner(),
                body=request_body,
            )
    else:
        resp = await imessage_send_v1_imessage_send_post.asyncio_detailed(
            client=client.get_inner(),
            body=request_body,
        )

    if resp.status_code != 202:
        raise SendError.from_response(int(resp.status_code), resp.content)
    parsed = json.loads(resp.content.decode("utf-8"))
    return SendResult(
        message_id=str(parsed["message_id"]),
        queued_at=str(parsed["queued_at"]),
    )


__all__ = ["SendError", "SendResult", "send"]
