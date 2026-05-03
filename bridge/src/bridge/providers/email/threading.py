"""IMAP THREAD response parser + opaque thread-id codec.

### THREAD response

`IMAP4.thread("REFERENCES", ...)` returns nested parenthesised lists:

    (1)(2 3)(4 (5 6) 7)(...)

Each top-level group is one thread. Inner parens denote branches inside a
thread. We flatten — the API does not surface branching in v1; callers
just get the linear list of messages in arrival order.

### Thread id codec

The thread id is an opaque token of the form

    base64-urlsafe( "{account}:{message_id_without_brackets}" )

Padding `=` is stripped. We embed the account so `GET /v1/email/threads/{id}`
can dispatch without an extra `?account=` query param. Callers should treat
the token as opaque.
"""

from __future__ import annotations

import base64
import logging

from bridge.errors import BadRequest

logger = logging.getLogger("bridge.providers.email.threading")


def parse_thread_response(raw: bytes | str) -> list[list[int]]:
    """Parse `(1)(2 3)(4 (5 6) 7)` style output. Branches are flattened.

    Returns one inner list per top-level thread, in the order the server
    returned. Caller is responsible for any subsequent ordering.
    """
    s = raw.decode("ascii", errors="replace") if isinstance(raw, bytes) else raw
    threads: list[list[int]] = []
    depth = 0
    cur_token = ""
    cur_thread: list[int] = []

    def flush_token() -> None:
        nonlocal cur_token
        if cur_token.strip():
            try:
                cur_thread.append(int(cur_token.strip()))
            except ValueError:
                logger.warning(
                    "thread_response_non_int_uid",
                    extra={"token": cur_token},
                )
            cur_token = ""

    for ch in s:
        if ch == "(":
            flush_token()
            depth += 1
            if depth == 1:
                cur_thread = []
        elif ch == ")":
            flush_token()
            depth -= 1
            if depth == 0:
                threads.append(cur_thread)
                cur_thread = []
        elif ch.isspace():
            flush_token()
        else:
            cur_token += ch
    return threads


def encode_thread_id(account: str, message_id: str) -> str:
    """Pack `(account, message_id)` into an opaque, URL-safe token."""
    cleaned = message_id.strip().lstrip("<").rstrip(">")
    payload = f"{account}:{cleaned}".encode()
    return base64.urlsafe_b64encode(payload).decode("ascii").rstrip("=")


def decode_thread_id(token: str) -> tuple[str, str]:
    """Inverse of `encode_thread_id`. Returns `(account, message_id)` with
    angle brackets restored. Raises `BadRequest` on malformed tokens."""
    padding = "=" * ((4 - len(token) % 4) % 4)
    try:
        payload = base64.urlsafe_b64decode((token + padding).encode("ascii"))
        text = payload.decode("utf-8")
    except (ValueError, UnicodeDecodeError) as exc:
        raise BadRequest(
            "Malformed email thread id.",
            details={"id": token},
        ) from exc
    if ":" not in text:
        raise BadRequest(
            "Malformed email thread id (missing separator).",
            details={"id": token},
        )
    account, message_id = text.split(":", 1)
    if not account or not message_id:
        raise BadRequest(
            "Malformed email thread id (empty component).",
            details={"id": token},
        )
    return account, f"<{message_id}>"
