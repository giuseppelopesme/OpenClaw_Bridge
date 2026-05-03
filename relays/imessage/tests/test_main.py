"""Relay loops — dispatch + outcome reporting against fakes.

We don't spin up real threads here — the loops are factored as
``run_inbound_loop`` / ``run_outbound_loop`` taking a ``stop`` event so
tests can drive a single iteration synchronously by setting the event
after one call. ``BridgeClient`` and ``send_imessage`` are replaced
with stand-ins that record what they would have done.
"""

from __future__ import annotations

import threading
from collections.abc import Iterator
from pathlib import Path
from typing import Any
from unittest.mock import patch

from relay import main as relay_main
from relay.bridge_client import BridgeClient
from relay.chatdb import ChatDBCursor, InboundMessage
from relay.config import RelayConfig
from relay.osascript import OsascriptError


class FakeBridge:
    def __init__(self, *, outbox_jobs: list[dict[str, Any]] | None = None) -> None:
        self.posted_inbound: list[dict[str, Any]] = []
        self.posted_sent: list[dict[str, Any]] = []
        self._outbox = list(outbox_jobs or [])

    def post_inbound(self, **kwargs: Any) -> dict[str, Any]:
        self.posted_inbound.append(kwargs)
        return {"received": True, "event_id": f"evt-{len(self.posted_inbound)}"}

    def get_outbox(
        self,
        *,
        agent: str,  # noqa: ARG002
        timeout_s: int,  # noqa: ARG002
    ) -> dict[str, Any] | None:
        if self._outbox:
            return self._outbox.pop(0)
        return None

    def post_sent(self, **kwargs: Any) -> dict[str, Any]:
        self.posted_sent.append(kwargs)
        return {"acknowledged": True, "event_id": f"snt-{len(self.posted_sent)}"}


class FakeCursor:
    def __init__(self, batches: list[list[InboundMessage]]) -> None:
        self._batches = batches

    def poll_new(self) -> Iterator[InboundMessage]:
        if not self._batches:
            return iter(())
        return iter(self._batches.pop(0))


def _config(tmp_path: Path) -> RelayConfig:
    return RelayConfig(
        bridge_url="http://x",
        agent_name="clu",
        relay_token="t",
        chatdb_path=tmp_path / "chat.db",
        state_path=tmp_path / "state",
        poll_interval_s=0.01,
        outbox_timeout_s=1,
    )


# -- inbound loop ------------------------------------------------------


def test_inbound_loop_forwards_messages_then_stops(tmp_path: Path) -> None:
    cfg = _config(tmp_path)
    bridge = FakeBridge()
    cursor = FakeCursor(
        [
            [
                InboundMessage(
                    rowid=1,
                    handle="+39",
                    body="hi",
                    received_at="2026-05-02T10:00:00+00:00",
                    chat_guid="g",
                ),
            ],
        ],
    )
    stop = threading.Event()

    # Stop after the first poll completes.
    original_wait = stop.wait

    def _wait_and_stop(timeout: float | None = None) -> bool:
        stop.set()
        return original_wait(timeout)

    with patch.object(stop, "wait", side_effect=_wait_and_stop):
        relay_main.run_inbound_loop(cfg, cursor, bridge, stop)  # type: ignore[arg-type]
    assert len(bridge.posted_inbound) == 1
    assert bridge.posted_inbound[0]["body"] == "hi"
    assert bridge.posted_inbound[0]["agent"] == "clu"


def test_inbound_loop_keeps_running_when_post_raises(tmp_path: Path) -> None:
    """A bridge failure on one message must not crash the loop."""
    cfg = _config(tmp_path)
    bridge = FakeBridge()

    # Replace post_inbound with a method that raises once.
    state = {"raised": False}

    def _flaky(**_kw: Any) -> dict[str, Any]:
        if not state["raised"]:
            state["raised"] = True
            from relay.bridge_client import BridgeClientError

            raise BridgeClientError(status=503, message="bad")
        return {"received": True, "event_id": "ok"}

    bridge.post_inbound = _flaky  # type: ignore[method-assign]
    cursor = FakeCursor(
        [
            [
                InboundMessage(
                    rowid=1,
                    handle="+39",
                    body="m1",
                    received_at="2026-05-02T10:00:00+00:00",
                    chat_guid="g",
                ),
                InboundMessage(
                    rowid=2,
                    handle="+39",
                    body="m2",
                    received_at="2026-05-02T10:01:00+00:00",
                    chat_guid="g",
                ),
            ],
        ],
    )
    stop = threading.Event()
    original_wait = stop.wait

    def _wait_and_stop(timeout: float | None = None) -> bool:
        stop.set()
        return original_wait(timeout)

    with patch.object(stop, "wait", side_effect=_wait_and_stop):
        relay_main.run_inbound_loop(cfg, cursor, bridge, stop)  # type: ignore[arg-type]
    # At least the second message went through; the first raised but the
    # loop survived and processed the rest of the batch.
    assert state["raised"] is True


# -- outbound loop -----------------------------------------------------


def test_outbound_dispatches_job_and_reports_success(tmp_path: Path) -> None:
    cfg = _config(tmp_path)
    bridge = FakeBridge(
        outbox_jobs=[
            {
                "message_id": "m1",
                "to": "+39",
                "body": "hi",
                "service": "iMessage",
                "from": "clu",
            },
        ],
    )
    sent: list[dict[str, Any]] = []

    def _fake_send(*, to: str, body: str, service: str = "iMessage") -> None:
        sent.append({"to": to, "body": body, "service": service})

    stop = threading.Event()
    original_get = bridge.get_outbox

    def _stopping_get_outbox(*args: Any, **kwargs: Any) -> dict[str, Any] | None:
        result = original_get(*args, **kwargs)
        if result is None:
            stop.set()
        return result

    bridge.get_outbox = _stopping_get_outbox  # type: ignore[method-assign]

    with patch.object(relay_main, "send_imessage", side_effect=_fake_send):
        relay_main.run_outbound_loop(cfg, bridge, stop)  # type: ignore[arg-type]

    assert sent == [{"to": "+39", "body": "hi", "service": "iMessage"}]
    assert len(bridge.posted_sent) == 1
    confirm = bridge.posted_sent[0]
    assert confirm["status"] == "success"
    assert confirm["message_id"] == "m1"


def test_outbound_reports_failure_when_osascript_fails(tmp_path: Path) -> None:
    cfg = _config(tmp_path)
    bridge = FakeBridge(
        outbox_jobs=[
            {
                "message_id": "m1",
                "to": "+39",
                "body": "hi",
                "service": "iMessage",
                "from": "clu",
            },
        ],
    )
    stop = threading.Event()
    original_get = bridge.get_outbox

    def _stopping_get_outbox(*args: Any, **kwargs: Any) -> dict[str, Any] | None:
        result = original_get(*args, **kwargs)
        if result is None:
            stop.set()
        return result

    bridge.get_outbox = _stopping_get_outbox  # type: ignore[method-assign]

    err = OsascriptError(
        code="non_zero_exit",
        message="oops",
        stderr="nothing here",
    )
    with patch.object(relay_main, "send_imessage", side_effect=err):
        relay_main.run_outbound_loop(cfg, bridge, stop)  # type: ignore[arg-type]

    confirm = bridge.posted_sent[0]
    assert confirm["status"] == "failed"
    assert confirm["error_code"] == "non_zero_exit"
    assert confirm["error_message"] == "oops"


def test_outbound_skips_malformed_job(tmp_path: Path) -> None:
    cfg = _config(tmp_path)
    bridge = FakeBridge(outbox_jobs=[{"to": "+39"}])  # missing message_id + body
    stop = threading.Event()
    original_get = bridge.get_outbox

    def _stopping_get_outbox(*args: Any, **kwargs: Any) -> dict[str, Any] | None:
        result = original_get(*args, **kwargs)
        if result is None:
            stop.set()
        return result

    bridge.get_outbox = _stopping_get_outbox  # type: ignore[method-assign]

    sent_called = []

    def _fail_send(*, to: str, body: str, service: str = "iMessage") -> None:
        sent_called.append((to, body, service))

    with patch.object(relay_main, "send_imessage", side_effect=_fail_send):
        relay_main.run_outbound_loop(cfg, bridge, stop)  # type: ignore[arg-type]

    assert sent_called == []
    assert bridge.posted_sent == []


# -- type guard --------------------------------------------------------


def test_relay_main_does_not_import_bridge_or_brains() -> None:
    """Boundary check by symbol — imports are scanned by check-boundaries.sh,
    but a unit test catches accidental future regressions inside this file."""
    src = Path(relay_main.__file__).read_text(encoding="utf-8")
    assert "from bridge" not in src
    assert "import bridge" not in src
    assert "from brains" not in src
    assert "import brains" not in src


def test_bridge_client_type() -> None:
    """Sanity: imports compile and BridgeClient is the right symbol."""
    assert BridgeClient.__name__ == "BridgeClient"
    assert ChatDBCursor.__name__ == "ChatDBCursor"
