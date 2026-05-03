"""RFC 5322 message bytes → `EmailMessage` dataclass.

Uses the stdlib `email` package (not `email.parser`-the-old-one — the
modern `email.message.EmailMessage` API). Bodies are extracted as text
and HTML parts; non-UTF-8 charsets are decoded best-effort with
`errors="replace"`.

Date headers are normalised to ISO 8601 UTC. Missing or unparseable
dates surface as the empty string — callers using them in sort keys
should fall back to the IMAP UID order.
"""

from __future__ import annotations

import logging
from datetime import UTC
from email import policy
from email.message import EmailMessage as _StdEmailMessage
from email.parser import BytesParser
from email.utils import parsedate_to_datetime

from bridge.providers.email.models import EmailMessage

logger = logging.getLogger("bridge.providers.email.parsing")


def parse_imap_message(uid: str, raw: bytes) -> EmailMessage:
    """Parse a raw RFC 822 byte blob (as returned by IMAP FETCH RFC822)
    into our `EmailMessage` dataclass.

    `uid` is the IMAP UID, used as the message id. Parsing failures fall
    back to a minimal record (empty body, raw headers we could read).
    """
    parser = BytesParser(_StdEmailMessage, policy=policy.default)
    msg = parser.parsebytes(raw)

    return EmailMessage(
        id=uid,
        message_id=_str(msg.get("Message-ID", "")),
        from_=_str(msg.get("From", "")),
        to=_split_addresses(msg.get("To", "")),
        cc=_split_addresses(msg.get("Cc", "")),
        subject=_str(msg.get("Subject", "")),
        date=_normalise_date(msg.get("Date")),
        body_text=_extract_body(msg, "text/plain"),
        body_html=_extract_body(msg, "text/html"),
        in_reply_to=(_str(msg.get("In-Reply-To")) or None),
        references=_split_message_ids(msg.get("References", "")),
    )


def _str(value: object) -> str:
    if value is None:
        return ""
    return str(value).strip()


def _split_addresses(header_value: object) -> list[str]:
    if not header_value:
        return []
    text = str(header_value).strip()
    if not text:
        return []
    # The modern `email` policy returns an `Address`-aware header; splitting
    # on commas is good enough for the API surface we expose.
    parts = [p.strip() for p in text.split(",")]
    return [p for p in parts if p]


def _split_message_ids(header_value: object) -> list[str]:
    if not header_value:
        return []
    text = str(header_value).strip()
    if not text:
        return []
    # References is a whitespace-separated list of `<msg-id>` tokens.
    return [tok.strip() for tok in text.split() if tok.strip()]


def _normalise_date(header_value: object) -> str:
    if not header_value:
        return ""
    text = str(header_value).strip()
    if not text:
        return ""
    try:
        dt = parsedate_to_datetime(text)
    except (TypeError, ValueError):
        logger.warning("email_date_unparseable", extra={"header": text})
        return ""
    if dt is None:
        return ""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return dt.astimezone(UTC).isoformat()


def _extract_body(msg: _StdEmailMessage, content_type: str) -> str | None:
    """Return the first body part matching `content_type`, or `None`."""
    try:
        part = msg.get_body(preferencelist=(content_type.split("/")[1],))
    except (KeyError, AttributeError):
        part = None
    if part is None:
        for sub in msg.walk():
            if sub.get_content_type() == content_type:
                part = sub
                break
    if part is None:
        return None
    try:
        payload = part.get_content()
    except (LookupError, KeyError, ValueError):
        # Fall back to raw payload decoding if the policy can't decode.
        raw = part.get_payload(decode=True)
        if not isinstance(raw, bytes):
            return None
        return raw.decode("utf-8", errors="replace")
    if isinstance(payload, bytes):
        return payload.decode("utf-8", errors="replace")
    return str(payload)
