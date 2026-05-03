"""Typed dataclasses shared across the email provider.

Accounts are loaded once from `~/.openclaw/email.toml` (server config) +
macOS Keychain (password). Threads and messages are constructed lazily by
the IMAP provider when the routes ask.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class EmailAccount:
    """Server config for one of the three known accounts.

    `name` is the route-level identifier (`glysk` | `lopes` | `whilesum`).
    `address` is the full email used for SMTP From and IMAP login.
    """

    name: str
    address: str
    imap_host: str
    imap_port: int
    smtp_host: str
    smtp_port: int


@dataclass(frozen=True)
class EmailMessage:
    """One RFC 5322 message, normalised for our API surface."""

    id: str
    """Stable per-(account, mailbox) UID — opaque to API callers."""

    message_id: str
    """RFC 5322 Message-ID header (with angle brackets)."""

    from_: str
    to: list[str]
    cc: list[str]
    subject: str
    date: str
    """ISO 8601 UTC, normalised from the Date header."""

    body_text: str | None
    body_html: str | None
    in_reply_to: str | None
    references: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class ThreadSummary:
    """Lightweight thread summary returned by `GET /v1/email/threads`."""

    id: str
    """Opaque thread id — base64-urlsafe(account:root_message_id)."""

    subject: str
    participants: list[str]
    message_count: int
    latest_at: str
    snippet: str
    """First ~200 chars of the latest message body, plain text."""


@dataclass(frozen=True)
class ThreadDetail:
    """Full thread + all messages, returned by `GET /v1/email/threads/{id}`."""

    id: str
    subject: str
    messages: list[EmailMessage]
