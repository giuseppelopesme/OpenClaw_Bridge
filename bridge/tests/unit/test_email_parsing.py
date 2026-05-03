"""RFC 5322 message → EmailMessage round-trip."""

from __future__ import annotations

from email.message import EmailMessage as StdEmailMessage

from bridge.providers.email.parsing import parse_imap_message


def _build(
    *,
    msg_id: str = "<m1@example.com>",
    from_: str = "alice@example.com",
    to: str = "bob@example.com",
    cc: str | None = None,
    subject: str = "Hello",
    date: str = "Fri, 02 May 2026 12:00:00 +0000",
    body_text: str | None = "Hi there",
    body_html: str | None = None,
    in_reply_to: str | None = None,
    references: str | None = None,
) -> bytes:
    msg = StdEmailMessage()
    msg["Message-ID"] = msg_id
    msg["From"] = from_
    msg["To"] = to
    if cc:
        msg["Cc"] = cc
    msg["Subject"] = subject
    msg["Date"] = date
    if in_reply_to:
        msg["In-Reply-To"] = in_reply_to
    if references:
        msg["References"] = references
    if body_text and body_html:
        msg.set_content(body_text)
        msg.add_alternative(body_html, subtype="html")
    elif body_html:
        msg.set_content(body_html, subtype="html")
    elif body_text:
        msg.set_content(body_text)
    return msg.as_bytes()


def test_parse_simple_text_message() -> None:
    raw = _build()
    parsed = parse_imap_message("42", raw)
    assert parsed.id == "42"
    assert parsed.message_id == "<m1@example.com>"
    assert parsed.from_ == "alice@example.com"
    assert parsed.to == ["bob@example.com"]
    assert parsed.cc == []
    assert parsed.subject == "Hello"
    assert parsed.date.startswith("2026-05-02T12:00:00")
    assert parsed.body_text and "Hi there" in parsed.body_text
    assert parsed.body_html is None
    assert parsed.in_reply_to is None
    assert parsed.references == []


def test_parse_multipart_alternative() -> None:
    raw = _build(body_text="text body", body_html="<p>html body</p>")
    parsed = parse_imap_message("1", raw)
    assert parsed.body_text and "text body" in parsed.body_text
    assert parsed.body_html and "html body" in parsed.body_html


def test_parse_references_header() -> None:
    raw = _build(
        in_reply_to="<a@x>",
        references="<root@x> <a@x>",
    )
    parsed = parse_imap_message("1", raw)
    assert parsed.in_reply_to == "<a@x>"
    assert parsed.references == ["<root@x>", "<a@x>"]


def test_parse_multiple_to_cc() -> None:
    raw = _build(to="a@x, b@y", cc="c@z, d@w")
    parsed = parse_imap_message("1", raw)
    assert parsed.to == ["a@x", "b@y"]
    assert parsed.cc == ["c@z", "d@w"]


def test_parse_unparseable_date_yields_empty_string() -> None:
    raw = _build(date="not a real date")
    parsed = parse_imap_message("1", raw)
    assert parsed.date == ""


def test_parse_naive_date_assumed_utc() -> None:
    raw = _build(date="Fri, 02 May 2026 14:30:00")  # no offset
    parsed = parse_imap_message("1", raw)
    assert parsed.date == "2026-05-02T14:30:00+00:00"
