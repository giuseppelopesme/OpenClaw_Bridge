"""SMTP provider — `send` only. Sync stdlib `smtplib`, wrapped in
`asyncio.to_thread` so the route handler stays async.

Connection model: open one SMTP per send (STARTTLS + login + send_message
+ quit). Persistent SMTP sessions are not worth the complexity at
human-cadence sending.

The bridge composes the message with stdlib `email.message.EmailMessage`,
sets a fresh Message-ID, and returns it to the caller alongside the
queued-at timestamp.
"""

from __future__ import annotations

import asyncio
import logging
import smtplib
from collections.abc import Callable
from datetime import UTC, datetime
from email.message import EmailMessage as StdEmailMessage
from email.utils import make_msgid
from typing import Any, Final

from bridge.errors import DependencyUnavailable
from bridge.providers.email.models import EmailAccount

logger = logging.getLogger("bridge.providers.email.smtp")

ClientFactory = Callable[[], Any]

_CMD_TIMEOUT_S: Final[float] = 10.0


class SMTPProvider:
    """One per email account. Stateless across requests."""

    def __init__(
        self,
        account: EmailAccount,
        password: str,
        *,
        client_factory: ClientFactory | None = None,
    ) -> None:
        self._account = account
        self._password = password
        self._factory: ClientFactory = client_factory or self._default_factory

    @property
    def account(self) -> EmailAccount:
        return self._account

    def _default_factory(self) -> Any:
        return smtplib.SMTP(
            self._account.smtp_host,
            self._account.smtp_port,
            timeout=_CMD_TIMEOUT_S,
        )

    async def send(
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
        """Send a message. Returns `(message_id, queued_at_iso)`.

        Either `body_text` or `body_html` is required. Both are accepted
        and result in a multipart/alternative message with text first.
        """
        if not body_text and not body_html:
            raise DependencyUnavailable(
                "Email send requires body_text or body_html.",
                details={"reason": "empty_body"},
            )
        return await asyncio.to_thread(
            self._sync_send,
            to,
            cc or [],
            bcc or [],
            subject,
            body_text,
            body_html,
            in_reply_to,
        )

    def _sync_send(
        self,
        to: list[str],
        cc: list[str],
        bcc: list[str],
        subject: str,
        body_text: str | None,
        body_html: str | None,
        in_reply_to: str | None,
    ) -> tuple[str, str]:
        msg = self._compose(to, cc, subject, body_text, body_html, in_reply_to)
        recipients = list(to) + list(cc) + list(bcc)
        try:
            client = self._factory()
        except OSError as exc:
            raise DependencyUnavailable(
                "SMTP connect failed.",
                details={"account": self._account.name, "error": str(exc)},
            ) from exc
        try:
            try:
                client.ehlo()
                client.starttls()
                client.ehlo()
                client.login(self._account.address, self._password)
                client.send_message(msg, to_addrs=recipients)
            except smtplib.SMTPException as exc:
                raise DependencyUnavailable(
                    "SMTP send failed.",
                    details={"account": self._account.name, "error": str(exc)},
                ) from exc
        finally:
            try:
                client.quit()
            except smtplib.SMTPException:
                logger.debug("smtp_quit_swallowed", exc_info=True)
        return msg["Message-ID"], datetime.now(UTC).isoformat()

    def _compose(
        self,
        to: list[str],
        cc: list[str],
        subject: str,
        body_text: str | None,
        body_html: str | None,
        in_reply_to: str | None,
    ) -> StdEmailMessage:
        msg = StdEmailMessage()
        msg["From"] = self._account.address
        msg["To"] = ", ".join(to)
        if cc:
            msg["Cc"] = ", ".join(cc)
        msg["Subject"] = subject
        domain = self._account.address.split("@", 1)[-1] or "localhost"
        msg["Message-ID"] = make_msgid(domain=domain)
        if in_reply_to:
            msg["In-Reply-To"] = in_reply_to
            msg["References"] = in_reply_to
        if body_text and body_html:
            msg.set_content(body_text)
            msg.add_alternative(body_html, subtype="html")
        elif body_html:
            msg.set_content(body_html, subtype="html")
        else:
            msg.set_content(body_text or "")
        return msg
