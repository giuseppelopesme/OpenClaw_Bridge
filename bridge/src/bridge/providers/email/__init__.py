"""Email providers — IMAP read + SMTP send for the three accounts.

The bridge talks to whatever IMAP/SMTP servers the operator configures via
`~/.openclaw/email.toml` (path overridable with `BRIDGE_EMAIL_CONFIG`).
Per-account passwords live in macOS Keychain under
`provider.email.{account}`. The three accounts in the v1 spec are
`glysk`, `lopes`, `whilesum`.

This package owns:

- `models.py` — typed dataclasses for accounts, messages, threads.
- `config.py` — TOML loader producing `EmailConfig`.
- `threading.py` — IMAP THREAD response parser + opaque thread-id codec.
- `parsing.py` — RFC 5322 message → `EmailMessage` dataclass.
- `imap.py` — `IMAPProvider` (one instance per account).
- `smtp.py` — `SMTPProvider` (one instance per account).

Both providers wrap the stdlib (`imaplib`, `smtplib`) via
`asyncio.to_thread` so the bridge stays async-clean without a heavyweight
async-IMAP dep. CLAUDE.md §"Tech stack (locked)" already includes the
threading bridge pattern (Session 2 chose it for SQLite); this is the
same idea.
"""

from bridge.providers.email.config import EmailConfig, load_email_config
from bridge.providers.email.imap import IMAPProvider
from bridge.providers.email.models import (
    EmailAccount,
    EmailMessage,
    ThreadDetail,
    ThreadSummary,
)
from bridge.providers.email.smtp import SMTPProvider

__all__ = [
    "EmailAccount",
    "EmailConfig",
    "EmailMessage",
    "IMAPProvider",
    "SMTPProvider",
    "ThreadDetail",
    "ThreadSummary",
    "load_email_config",
]
