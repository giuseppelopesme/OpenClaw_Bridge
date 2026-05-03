"""IMAPProvider — happy paths and error mapping with a fake imaplib client.

The fake stands in for `imaplib.IMAP4` / `IMAP4_SSL` and exposes only the
methods the provider uses: login, select, thread, uid (SEARCH), fetch,
noop, logout. Tests instantiate `IMAPProvider` with a `client_factory`
that returns the fake.
"""

from __future__ import annotations

import imaplib
from collections.abc import Callable
from email.message import EmailMessage as StdEmailMessage
from typing import Any

import pytest
from bridge.errors import DependencyUnavailable, NotFound
from bridge.providers.email.imap import IMAPProvider
from bridge.providers.email.models import EmailAccount

ACCOUNT = EmailAccount(
    name="glysk",
    address="giuseppe@glysk.dev",
    imap_host="imap.example.com",
    imap_port=993,
    smtp_host="smtp.example.com",
    smtp_port=587,
)


def _build_message_bytes(
    *,
    msg_id: str,
    subject: str,
    from_: str = "alice@example.com",
    body: str = "hello",
    references: str | None = None,
    date: str = "Fri, 02 May 2026 12:00:00 +0000",
) -> bytes:
    msg = StdEmailMessage()
    msg["Message-ID"] = msg_id
    msg["From"] = from_
    msg["To"] = "bob@example.com"
    msg["Subject"] = subject
    msg["Date"] = date
    if references:
        msg["References"] = references
    msg.set_content(body)
    return msg.as_bytes()


class FakeIMAP:
    """Minimal IMAP4 stand-in. Configurable per-test via `responses`."""

    def __init__(self) -> None:
        self.login_called = False
        self.logout_called = False
        self.noop_called = False
        self.thread_response: tuple[str, list[bytes]] = ("OK", [b"(1 2)(3)"])
        self.search_response: tuple[str, list[bytes]] = ("OK", [b""])
        self.messages: dict[int, bytes] = {}
        self.thread_should_raise: imaplib.IMAP4.error | None = None
        self.login_should_fail: bool = False
        self.connect_should_fail: bool = False

    # --- imaplib surface --------------------------------------------------

    def login(self, _user: str, _password: str) -> tuple[str, list[bytes]]:
        if self.login_should_fail:
            raise imaplib.IMAP4.error("authentication failed")
        self.login_called = True
        return "OK", [b"LOGIN OK"]

    def logout(self) -> tuple[str, list[bytes]]:
        self.logout_called = True
        return "BYE", [b"LOGOUT"]

    def select(
        self,
        _mailbox: str = "INBOX",
        readonly: bool = False,
    ) -> tuple[str, list[bytes]]:
        _ = readonly
        return "OK", [b"123"]

    def thread(
        self,
        _algo: str,
        _charset: str,
        *_criteria: str,
    ) -> tuple[str, list[bytes]]:
        if self.thread_should_raise is not None:
            raise self.thread_should_raise
        return self.thread_response

    def uid(self, _cmd: str, *_args: str) -> tuple[str, list[bytes]]:
        return self.search_response

    def fetch(
        self,
        uid_bytes: bytes,
        _items: str,
    ) -> tuple[str, list[Any]]:
        uid = int(uid_bytes.decode("ascii"))
        if uid not in self.messages:
            return "NO", [b""]
        return "OK", [(b"header", self.messages[uid])]

    def noop(self) -> tuple[str, list[bytes]]:
        self.noop_called = True
        return "OK", [b"NOOP"]


def _provider_with(fake: FakeIMAP) -> IMAPProvider:
    return IMAPProvider(ACCOUNT, "secret", client_factory=lambda: fake)


def _factory_failing() -> Callable[[], Any]:
    def _f() -> Any:
        raise OSError("connection refused")

    return _f


# --- list_threads ----------------------------------------------------


@pytest.mark.asyncio
async def test_list_threads_happy_path() -> None:
    fake = FakeIMAP()
    fake.thread_response = ("OK", [b"(1 2)(3)"])
    fake.messages = {
        1: _build_message_bytes(msg_id="<root1@x>", subject="Project A", body="root body"),
        2: _build_message_bytes(
            msg_id="<reply1@x>",
            subject="Re: Project A",
            from_="bob@example.com",
            body="reply body",
            references="<root1@x>",
        ),
        3: _build_message_bytes(msg_id="<root2@x>", subject="Project B", body="solo"),
    }
    p = _provider_with(fake)
    threads = await p.list_threads()
    # Newest-first: thread (3) first, then (1 2).
    assert len(threads) == 2
    assert threads[0].subject == "Project B"
    assert threads[0].message_count == 1
    assert threads[1].subject == "Project A"
    assert threads[1].message_count == 2
    # Snippet from latest message of multi-thread.
    assert "reply body" in threads[1].snippet
    assert fake.login_called
    assert fake.logout_called


@pytest.mark.asyncio
async def test_list_threads_empty_response_returns_empty() -> None:
    fake = FakeIMAP()
    fake.thread_response = ("OK", [b""])
    p = _provider_with(fake)
    assert await p.list_threads() == []


@pytest.mark.asyncio
async def test_list_threads_respects_limit() -> None:
    fake = FakeIMAP()
    fake.thread_response = ("OK", [b"(1)(2)(3)(4)(5)"])
    for i in range(1, 6):
        fake.messages[i] = _build_message_bytes(msg_id=f"<m{i}@x>", subject=f"S{i}")
    p = _provider_with(fake)
    threads = await p.list_threads(limit=3)
    assert len(threads) == 3


@pytest.mark.asyncio
async def test_list_threads_login_failure_raises_dependency_unavailable() -> None:
    fake = FakeIMAP()
    fake.login_should_fail = True
    p = _provider_with(fake)
    with pytest.raises(DependencyUnavailable):
        await p.list_threads()


@pytest.mark.asyncio
async def test_list_threads_thread_command_failure() -> None:
    fake = FakeIMAP()
    fake.thread_should_raise = imaplib.IMAP4.error("THREAD not supported")
    p = _provider_with(fake)
    with pytest.raises(DependencyUnavailable):
        await p.list_threads()


@pytest.mark.asyncio
async def test_list_threads_connect_failure_raises_dependency_unavailable() -> None:
    p = IMAPProvider(ACCOUNT, "secret", client_factory=_factory_failing())
    with pytest.raises(DependencyUnavailable):
        await p.list_threads()


@pytest.mark.asyncio
async def test_list_threads_invalid_before_raises_dependency_unavailable() -> None:
    fake = FakeIMAP()
    p = _provider_with(fake)
    with pytest.raises(DependencyUnavailable):
        await p.list_threads(before="not-a-date")


# --- get_thread -----------------------------------------------------


@pytest.mark.asyncio
async def test_get_thread_returns_messages_in_date_order() -> None:
    fake = FakeIMAP()
    fake.search_response = ("OK", [b"5 7"])
    fake.messages = {
        5: _build_message_bytes(
            msg_id="<root@x>",
            subject="Subject",
            date="Fri, 02 May 2026 12:00:00 +0000",
            body="root",
        ),
        7: _build_message_bytes(
            msg_id="<reply@x>",
            subject="Re: Subject",
            date="Fri, 02 May 2026 14:00:00 +0000",
            body="reply",
            references="<root@x>",
        ),
    }
    p = _provider_with(fake)
    detail = await p.get_thread("<root@x>")
    assert len(detail.messages) == 2
    assert detail.messages[0].body_text and "root" in detail.messages[0].body_text
    assert detail.messages[1].body_text and "reply" in detail.messages[1].body_text


@pytest.mark.asyncio
async def test_get_thread_empty_search_raises_not_found() -> None:
    fake = FakeIMAP()
    fake.search_response = ("OK", [b""])
    p = _provider_with(fake)
    with pytest.raises(NotFound):
        await p.get_thread("<missing@x>")


@pytest.mark.asyncio
async def test_get_thread_search_failure_raises_dependency_unavailable() -> None:
    class FakeWithSearchFail(FakeIMAP):
        def uid(self, _cmd: str, *_args: str) -> tuple[str, list[bytes]]:
            raise imaplib.IMAP4.error("nope")

    fake = FakeWithSearchFail()
    p = _provider_with(fake)
    with pytest.raises(DependencyUnavailable):
        await p.get_thread("<x@x>")


# --- healthcheck ----------------------------------------------------


@pytest.mark.asyncio
async def test_healthcheck_ok() -> None:
    fake = FakeIMAP()
    p = _provider_with(fake)
    assert await p.healthcheck() == "ok"
    assert fake.noop_called


@pytest.mark.asyncio
async def test_healthcheck_login_failure_returns_down() -> None:
    fake = FakeIMAP()
    fake.login_should_fail = True
    p = _provider_with(fake)
    assert await p.healthcheck() == "down"


@pytest.mark.asyncio
async def test_healthcheck_connect_failure_returns_down() -> None:
    p = IMAPProvider(ACCOUNT, "secret", client_factory=_factory_failing())
    assert await p.healthcheck() == "down"
