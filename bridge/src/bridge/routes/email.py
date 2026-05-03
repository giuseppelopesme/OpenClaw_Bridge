"""Email endpoints — list threads, get thread, send.

`GET  /v1/email/threads`         scope `email:read`
`GET  /v1/email/threads/{id}`    scope `email:read`
`POST /v1/email/send`            scope `email:send`  (rate-limited)

Account selection: `?account=glysk|lopes|whilesum` on the list endpoint
and in the body of POST /send. The thread id encodes the account, so
`GET /v1/email/threads/{id}` doesn't need it as a separate parameter.

Provider lookup: `app.state.email_imap_providers[name]` and
`app.state.email_smtp_providers[name]`. Missing entries (no Keychain
password, no email.toml entry) → 502 `dependency_unavailable`.
"""

from __future__ import annotations

import logging
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Path, Query, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from bridge.auth import AuthContext, require_scope
from bridge.errors import BadRequest, DependencyUnavailable
from bridge.providers.email.imap import IMAPProvider
from bridge.providers.email.models import (
    EmailMessage,
    ThreadDetail,
    ThreadSummary,
)
from bridge.providers.email.smtp import SMTPProvider
from bridge.providers.email.threading import decode_thread_id
from bridge.ratelimit import require_rate

logger = logging.getLogger("bridge.routes.email")

router = APIRouter(tags=["email"])

AccountName = Literal["glysk", "lopes", "whilesum"]


class _ThreadOut(BaseModel):
    id: str
    subject: str
    participants: list[str]
    message_count: int
    latest_at: str
    snippet: str


class EmailThreadsListResponse(BaseModel):
    threads: list[_ThreadOut]


class _MessageOut(BaseModel):
    id: str
    message_id: str
    from_: str = Field(alias="from", serialization_alias="from")
    to: list[str]
    cc: list[str]
    subject: str
    date: str
    body_text: str | None = None
    body_html: str | None = None
    in_reply_to: str | None = None
    references: list[str] = Field(default_factory=list)

    model_config = {"populate_by_name": True}


class EmailThreadDetailResponse(BaseModel):
    id: str
    subject: str
    messages: list[_MessageOut]


class EmailSendRequest(BaseModel):
    account: AccountName
    to: list[str] = Field(min_length=1)
    cc: list[str] = Field(default_factory=list)
    bcc: list[str] = Field(default_factory=list)
    subject: str = Field(min_length=1)
    body_text: str | None = None
    body_html: str | None = None
    in_reply_to: str | None = None


def _check_addresses(label: str, values: list[str]) -> None:
    """Light validation: every address must contain `@`. SMTP rejects the
    rest at send time. Avoids pulling in `email-validator` for what is a
    basic sanity check."""
    for v in values:
        if "@" not in v or v.startswith("@") or v.endswith("@"):
            raise BadRequest(
                f"Invalid email address in {label}.",
                details={"field": label, "value": v},
            )


class EmailSendResponse(BaseModel):
    message_id: str
    queued_at: str


def _get_imap(request: Request, account: str) -> IMAPProvider:
    providers: dict[str, IMAPProvider] = request.app.state.email_imap_providers
    provider = providers.get(account)
    if provider is None:
        raise DependencyUnavailable(
            "Email account not configured.",
            details={"account": account, "missing": "imap_provider"},
        )
    return provider


def _get_smtp(request: Request, account: str) -> SMTPProvider:
    providers: dict[str, SMTPProvider] = request.app.state.email_smtp_providers
    provider = providers.get(account)
    if provider is None:
        raise DependencyUnavailable(
            "Email account not configured.",
            details={"account": account, "missing": "smtp_provider"},
        )
    return provider


def _summary_to_out(s: ThreadSummary) -> _ThreadOut:
    return _ThreadOut(
        id=s.id,
        subject=s.subject,
        participants=s.participants,
        message_count=s.message_count,
        latest_at=s.latest_at,
        snippet=s.snippet,
    )


def _message_to_out(m: EmailMessage) -> _MessageOut:
    # `from_` is the Python attribute; `from` is the JSON key per the spec.
    # Build via the alias since mypy cannot reconcile the keyword.
    return _MessageOut.model_validate(
        {
            "id": m.id,
            "message_id": m.message_id,
            "from": m.from_,
            "to": m.to,
            "cc": m.cc,
            "subject": m.subject,
            "date": m.date,
            "body_text": m.body_text,
            "body_html": m.body_html,
            "in_reply_to": m.in_reply_to,
            "references": m.references,
        },
    )


def _detail_to_out(d: ThreadDetail) -> EmailThreadDetailResponse:
    return EmailThreadDetailResponse(
        id=d.id,
        subject=d.subject,
        messages=[_message_to_out(m) for m in d.messages],
    )


@router.get("/v1/email/threads", response_model=EmailThreadsListResponse)
async def list_threads(
    request: Request,
    account: Annotated[AccountName, Query()],
    _auth: Annotated[AuthContext, Depends(require_scope("email:read"))],
    query: Annotated[str | None, Query()] = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
    before: Annotated[str | None, Query()] = None,
) -> EmailThreadsListResponse:
    provider = _get_imap(request, account)
    summaries = await provider.list_threads(query=query, limit=limit, before=before)
    return EmailThreadsListResponse(
        threads=[_summary_to_out(s) for s in summaries],
    )


@router.get("/v1/email/threads/{thread_id}", response_model=EmailThreadDetailResponse)
async def get_thread(
    request: Request,
    thread_id: Annotated[str, Path(min_length=1)],
    _auth: Annotated[AuthContext, Depends(require_scope("email:read"))],
) -> EmailThreadDetailResponse:
    account, root_message_id = decode_thread_id(thread_id)
    provider = _get_imap(request, account)
    detail = await provider.get_thread(root_message_id)
    return _detail_to_out(detail)


@router.post("/v1/email/send", status_code=202)
async def send_email(
    request: Request,
    body: EmailSendRequest,
    _auth: Annotated[AuthContext, Depends(require_scope("email:send"))],
    _rate: Annotated[AuthContext, Depends(require_rate("email:send"))],
) -> JSONResponse:
    _check_addresses("to", body.to)
    _check_addresses("cc", body.cc)
    _check_addresses("bcc", body.bcc)
    provider = _get_smtp(request, body.account)
    message_id, queued_at = await provider.send(
        to=body.to,
        cc=body.cc,
        bcc=body.bcc,
        subject=body.subject,
        body_text=body.body_text,
        body_html=body.body_html,
        in_reply_to=body.in_reply_to,
    )
    payload = EmailSendResponse(message_id=message_id, queued_at=queued_at).model_dump()
    return JSONResponse(status_code=202, content=payload)
