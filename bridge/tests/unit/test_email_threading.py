"""IMAP THREAD response parser + thread-id codec."""

from __future__ import annotations

import pytest
from bridge.errors import BadRequest
from bridge.providers.email.threading import (
    decode_thread_id,
    encode_thread_id,
    parse_thread_response,
)


def test_parse_thread_response_flat() -> None:
    assert parse_thread_response("(1)(2)(3)") == [[1], [2], [3]]


def test_parse_thread_response_grouped() -> None:
    assert parse_thread_response("(1 2 3)(4 5)") == [[1, 2, 3], [4, 5]]


def test_parse_thread_response_branched_is_flattened() -> None:
    # `(1 (2 3) 4)` describes a tree with branch — we flatten to [1,2,3,4].
    assert parse_thread_response("(1 (2 3) 4)") == [[1, 2, 3, 4]]


def test_parse_thread_response_nested_branches() -> None:
    assert parse_thread_response("(1 (2 (3 4) 5) 6)(7 8)") == [
        [1, 2, 3, 4, 5, 6],
        [7, 8],
    ]


def test_parse_thread_response_empty() -> None:
    assert parse_thread_response("") == []
    assert parse_thread_response(b"") == []


def test_parse_thread_response_bytes_input() -> None:
    assert parse_thread_response(b"(1 2)(3)") == [[1, 2], [3]]


def test_thread_id_round_trip() -> None:
    token = encode_thread_id("glysk", "<abc123@example.com>")
    account, mid = decode_thread_id(token)
    assert account == "glysk"
    assert mid == "<abc123@example.com>"


def test_thread_id_strips_brackets_on_encode() -> None:
    a = encode_thread_id("glysk", "<abc@x.y>")
    b = encode_thread_id("glysk", "abc@x.y")
    assert a == b


def test_thread_id_decode_rejects_garbage() -> None:
    with pytest.raises(BadRequest):
        decode_thread_id("not-base64-!!!")


def test_thread_id_decode_rejects_missing_separator() -> None:
    import base64

    bad = base64.urlsafe_b64encode(b"no-separator-here").decode("ascii").rstrip("=")
    with pytest.raises(BadRequest):
        decode_thread_id(bad)
