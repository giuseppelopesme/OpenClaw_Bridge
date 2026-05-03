"""Email HTTP endpoints — scope, dispatch, error envelopes."""

from __future__ import annotations

from typing import Any

from _support import TokenFixture
from bridge.providers.email.imap import IMAPProvider
from bridge.providers.email.models import (
    EmailAccount,
    EmailMessage,
    ThreadDetail,
    ThreadSummary,
)
from bridge.providers.email.smtp import SMTPProvider
from bridge.providers.email.threading import encode_thread_id
from fastapi.testclient import TestClient

AUTH_OK = {"Authorization": "Bearer dev-token-email"}

ACCOUNT = EmailAccount(
    name="glysk",
    address="giuseppe@glysk.dev",
    imap_host="imap.example.com",
    imap_port=993,
    smtp_host="smtp.example.com",
    smtp_port=587,
)


class FakeIMAP(IMAPProvider):
    """Subclass that overrides the network methods entirely."""

    def __init__(
        self,
        *,
        threads: list[ThreadSummary] | None = None,
        detail: ThreadDetail | None = None,
        raise_on_get: Exception | None = None,
    ) -> None:
        super().__init__(ACCOUNT, "secret", client_factory=lambda: object())
        self._threads = threads or []
        self._detail = detail
        self._raise_on_get = raise_on_get

    async def list_threads(  # type: ignore[override]
        self,
        *,
        query: str | None = None,
        limit: int = 20,
        before: str | None = None,
    ) -> list[ThreadSummary]:
        _ = (query, limit, before)
        return self._threads

    async def get_thread(self, root_message_id: str) -> ThreadDetail:  # type: ignore[override]
        if self._raise_on_get is not None:
            raise self._raise_on_get
        assert self._detail is not None
        return self._detail


class FakeSMTP(SMTPProvider):
    def __init__(self, *, raise_on_send: Exception | None = None) -> None:
        super().__init__(ACCOUNT, "secret", client_factory=lambda: object())
        self.captured: dict[str, Any] = {}
        self._raise = raise_on_send

    async def send(  # type: ignore[override]
        self,
        *,
        to: list[str],
        cc: list[str] | None = None,
        bcc: list[str] | None = None,
        subject: str,
        body_text: str | None = None,
        body_html: str | None = None,
        in_reply_to: str | None = None,
    ) -> tuple[str, str]:
        if self._raise is not None:
            raise self._raise
        self.captured = {
            "to": to,
            "cc": cc,
            "bcc": bcc,
            "subject": subject,
            "body_text": body_text,
            "body_html": body_html,
            "in_reply_to": in_reply_to,
        }
        return "<fake-message-id@example.com>", "2026-05-02T12:00:00+00:00"


def _install_imap(client: TestClient, account: str, provider: IMAPProvider) -> None:
    client.app.state.email_imap_providers[account] = provider


def _install_smtp(client: TestClient, account: str, provider: SMTPProvider) -> None:
    client.app.state.email_smtp_providers[account] = provider


# --- /v1/email/threads ----------------------------------------------------


def test_list_threads_happy_path(
    client: TestClient,
    tokens: list[TokenFixture],  # noqa: ARG001
) -> None:
    summary = ThreadSummary(
        id=encode_thread_id("glysk", "<root@x>"),
        subject="Project A",
        participants=["alice@example.com"],
        message_count=2,
        latest_at="2026-05-02T14:00:00+00:00",
        snippet="reply body",
    )
    _install_imap(client, "glysk", FakeIMAP(threads=[summary]))
    resp = client.get("/v1/email/threads?account=glysk", headers=AUTH_OK)
    assert resp.status_code == 200
    body = resp.json()
    assert len(body["threads"]) == 1
    assert body["threads"][0]["subject"] == "Project A"


def test_list_threads_unknown_account_returns_422(client: TestClient) -> None:
    resp = client.get("/v1/email/threads?account=fancy", headers=AUTH_OK)
    assert resp.status_code == 422


def test_list_threads_account_not_configured_returns_502(
    client: TestClient,
    tokens: list[TokenFixture],  # noqa: ARG001
) -> None:
    # No provider installed for "glysk" → 502.
    resp = client.get("/v1/email/threads?account=glysk", headers=AUTH_OK)
    assert resp.status_code == 502
    assert resp.json()["error"]["code"] == "dependency_unavailable"


def test_list_threads_requires_read_scope(client: TestClient) -> None:
    resp = client.get(
        "/v1/email/threads?account=glysk",
        headers={"Authorization": "Bearer dev-token-empty"},
    )
    assert resp.status_code == 403


# --- /v1/email/threads/{id} -----------------------------------------------


def test_get_thread_happy_path(
    client: TestClient,
    tokens: list[TokenFixture],  # noqa: ARG001
) -> None:
    msg = EmailMessage(
        id="42",
        message_id="<root@x>",
        from_="alice@example.com",
        to=["bob@example.com"],
        cc=[],
        subject="Project A",
        date="2026-05-02T12:00:00+00:00",
        body_text="hi",
        body_html=None,
        in_reply_to=None,
        references=[],
    )
    detail = ThreadDetail(
        id=encode_thread_id("glysk", "<root@x>"),
        subject="Project A",
        messages=[msg],
    )
    _install_imap(client, "glysk", FakeIMAP(detail=detail))
    thread_id = encode_thread_id("glysk", "<root@x>")
    resp = client.get(f"/v1/email/threads/{thread_id}", headers=AUTH_OK)
    assert resp.status_code == 200
    body = resp.json()
    assert body["subject"] == "Project A"
    assert body["messages"][0]["from"] == "alice@example.com"
    assert body["messages"][0]["message_id"] == "<root@x>"


def test_get_thread_malformed_id_returns_400(
    client: TestClient,
    tokens: list[TokenFixture],  # noqa: ARG001
) -> None:
    resp = client.get("/v1/email/threads/!!!not-base64!!!", headers=AUTH_OK)
    assert resp.status_code == 400
    assert resp.json()["error"]["code"] == "bad_request"


def test_get_thread_unknown_account_returns_502(
    client: TestClient,
    tokens: list[TokenFixture],  # noqa: ARG001
) -> None:
    thread_id = encode_thread_id("glysk", "<x@x>")
    resp = client.get(f"/v1/email/threads/{thread_id}", headers=AUTH_OK)
    assert resp.status_code == 502


def test_get_thread_requires_read_scope(client: TestClient) -> None:
    thread_id = encode_thread_id("glysk", "<x@x>")
    resp = client.get(
        f"/v1/email/threads/{thread_id}",
        headers={"Authorization": "Bearer dev-token-empty"},
    )
    assert resp.status_code == 403


# --- /v1/email/send -------------------------------------------------------


def test_send_happy_path(
    client: TestClient,
    tokens: list[TokenFixture],  # noqa: ARG001
) -> None:
    fake = FakeSMTP()
    _install_smtp(client, "glysk", fake)
    resp = client.post(
        "/v1/email/send",
        json={
            "account": "glysk",
            "to": ["bob@example.com"],
            "subject": "Hi",
            "body_text": "hello",
        },
        headers=AUTH_OK,
    )
    assert resp.status_code == 202
    body = resp.json()
    assert body["message_id"] == "<fake-message-id@example.com>"
    assert "queued_at" in body
    assert fake.captured["subject"] == "Hi"


def test_send_invalid_address_returns_400(
    client: TestClient,
    tokens: list[TokenFixture],  # noqa: ARG001
) -> None:
    _install_smtp(client, "glysk", FakeSMTP())
    resp = client.post(
        "/v1/email/send",
        json={
            "account": "glysk",
            "to": ["nope-no-at-sign"],
            "subject": "Hi",
            "body_text": "hello",
        },
        headers=AUTH_OK,
    )
    assert resp.status_code == 400
    assert resp.json()["error"]["code"] == "bad_request"


def test_send_account_not_configured_returns_502(
    client: TestClient,
    tokens: list[TokenFixture],  # noqa: ARG001
) -> None:
    resp = client.post(
        "/v1/email/send",
        json={
            "account": "lopes",
            "to": ["bob@example.com"],
            "subject": "Hi",
            "body_text": "hello",
        },
        headers=AUTH_OK,
    )
    assert resp.status_code == 502


def test_send_requires_send_scope(client: TestClient) -> None:
    resp = client.post(
        "/v1/email/send",
        json={
            "account": "glysk",
            "to": ["bob@example.com"],
            "subject": "Hi",
            "body_text": "hello",
        },
        headers={"Authorization": "Bearer dev-token-empty"},
    )
    assert resp.status_code == 403


def test_send_validation_failure_when_to_empty(
    client: TestClient,
    tokens: list[TokenFixture],  # noqa: ARG001
) -> None:
    _install_smtp(client, "glysk", FakeSMTP())
    resp = client.post(
        "/v1/email/send",
        json={
            "account": "glysk",
            "to": [],
            "subject": "Hi",
            "body_text": "hello",
        },
        headers=AUTH_OK,
    )
    assert resp.status_code == 422
