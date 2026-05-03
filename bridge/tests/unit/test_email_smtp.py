"""SMTPProvider — composition + send paths against a fake smtplib client."""

from __future__ import annotations

import smtplib
from email.message import EmailMessage as StdEmailMessage
from typing import Any

import pytest
from bridge.errors import DependencyUnavailable
from bridge.providers.email.models import EmailAccount
from bridge.providers.email.smtp import SMTPProvider

ACCOUNT = EmailAccount(
    name="glysk",
    address="giuseppe@glysk.dev",
    imap_host="imap.example.com",
    imap_port=993,
    smtp_host="smtp.example.com",
    smtp_port=587,
)


class FakeSMTP:
    def __init__(self) -> None:
        self.ehlo_called = 0
        self.starttls_called = False
        self.login_called = False
        self.quit_called = False
        self.sent: list[tuple[StdEmailMessage, list[str]]] = []
        self.send_should_raise: smtplib.SMTPException | None = None
        self.login_should_raise: smtplib.SMTPException | None = None

    def ehlo(self) -> None:
        self.ehlo_called += 1

    def starttls(self) -> None:
        self.starttls_called = True

    def login(self, _user: str, _password: str) -> None:
        if self.login_should_raise is not None:
            raise self.login_should_raise
        self.login_called = True

    def send_message(
        self,
        msg: StdEmailMessage,
        to_addrs: list[str] | None = None,
    ) -> dict[str, Any]:
        if self.send_should_raise is not None:
            raise self.send_should_raise
        self.sent.append((msg, list(to_addrs or [])))
        return {}

    def quit(self) -> None:
        self.quit_called = True


def _provider_with(fake: FakeSMTP) -> SMTPProvider:
    return SMTPProvider(ACCOUNT, "secret", client_factory=lambda: fake)


@pytest.mark.asyncio
async def test_send_text_only_happy_path() -> None:
    fake = FakeSMTP()
    p = _provider_with(fake)
    message_id, queued_at = await p.send(
        to=["bob@example.com"],
        subject="Hi",
        body_text="hello there",
    )
    assert fake.starttls_called
    assert fake.login_called
    assert fake.quit_called
    assert message_id.startswith("<") and message_id.endswith(">")
    assert "T" in queued_at  # ISO 8601
    msg, recipients = fake.sent[0]
    assert msg["From"] == ACCOUNT.address
    assert msg["To"] == "bob@example.com"
    assert msg["Subject"] == "Hi"
    assert recipients == ["bob@example.com"]


@pytest.mark.asyncio
async def test_send_includes_cc_and_bcc_in_recipients() -> None:
    fake = FakeSMTP()
    p = _provider_with(fake)
    await p.send(
        to=["a@x"],
        cc=["b@x"],
        bcc=["c@x"],
        subject="s",
        body_text="t",
    )
    _, recipients = fake.sent[0]
    assert recipients == ["a@x", "b@x", "c@x"]


@pytest.mark.asyncio
async def test_send_html_alternative_when_both_bodies_provided() -> None:
    fake = FakeSMTP()
    p = _provider_with(fake)
    await p.send(
        to=["a@x"],
        subject="s",
        body_text="text part",
        body_html="<p>html part</p>",
    )
    msg, _ = fake.sent[0]
    assert msg.is_multipart()


@pytest.mark.asyncio
async def test_send_in_reply_to_sets_headers() -> None:
    fake = FakeSMTP()
    p = _provider_with(fake)
    await p.send(
        to=["a@x"],
        subject="re",
        body_text="t",
        in_reply_to="<orig@x>",
    )
    msg, _ = fake.sent[0]
    assert msg["In-Reply-To"] == "<orig@x>"
    assert msg["References"] == "<orig@x>"


@pytest.mark.asyncio
async def test_send_empty_body_raises_dependency_unavailable() -> None:
    fake = FakeSMTP()
    p = _provider_with(fake)
    with pytest.raises(DependencyUnavailable):
        await p.send(to=["a@x"], subject="s")


@pytest.mark.asyncio
async def test_send_smtp_failure_maps_to_dependency_unavailable() -> None:
    fake = FakeSMTP()
    fake.send_should_raise = smtplib.SMTPRecipientsRefused({"a@x": (550, b"go away")})
    p = _provider_with(fake)
    with pytest.raises(DependencyUnavailable):
        await p.send(to=["a@x"], subject="s", body_text="t")


@pytest.mark.asyncio
async def test_send_login_failure_maps_to_dependency_unavailable() -> None:
    fake = FakeSMTP()
    fake.login_should_raise = smtplib.SMTPAuthenticationError(535, b"bad creds")
    p = _provider_with(fake)
    with pytest.raises(DependencyUnavailable):
        await p.send(to=["a@x"], subject="s", body_text="t")


@pytest.mark.asyncio
async def test_send_connect_failure_maps_to_dependency_unavailable() -> None:
    def _failing() -> Any:
        raise OSError("no route to host")

    p = SMTPProvider(ACCOUNT, "secret", client_factory=_failing)
    with pytest.raises(DependencyUnavailable):
        await p.send(to=["a@x"], subject="s", body_text="t")
