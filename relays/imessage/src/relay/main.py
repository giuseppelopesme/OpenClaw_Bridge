"""Relay process entrypoint — two threads, one per direction.

Inbound thread: every ``poll_interval_s`` seconds it scans chat.db via
``ChatDBCursor.poll_new`` and POSTs each new message to the bridge's
``/v1/imessage/inbound``.

Outbound thread: long-polls ``GET /v1/imessage/outbox`` (the bridge's
BLPOP-backed endpoint), sends via osascript, and POSTs the outcome to
``/v1/imessage/sent``.

SIGTERM / SIGINT: both threads notice the stop event, exit cleanly. The
outbox thread does *not* drain in-flight Redis BLPOP — the bridge will
return 204 on next pass, and the queued job remains for the next relay
session.
"""

from __future__ import annotations

import json
import logging
import signal
import sys
import threading
from datetime import UTC, datetime
from types import FrameType

from relay.bridge_client import BridgeClient, BridgeClientError
from relay.chatdb import ChatDBCursor, InboundMessage
from relay.config import RelayConfig
from relay.osascript import OsascriptError, send_imessage

logger = logging.getLogger("relay.main")


def _now_iso() -> str:
    return datetime.now(UTC).isoformat()


def _setup_logging() -> None:
    """Configure structured JSON-ish logging to stderr.

    The relay does not depend on the bridge's logging_setup module
    (boundaries forbid the import), so this is a small standalone
    setup mirroring the bridge's stderr-JSON convention.
    """
    handler = logging.StreamHandler(sys.stderr)
    handler.setFormatter(_JsonFormatter())
    root = logging.getLogger()
    root.handlers[:] = [handler]
    root.setLevel(logging.INFO)


class _JsonFormatter(logging.Formatter):
    _RESERVED = {
        "name",
        "msg",
        "args",
        "levelname",
        "levelno",
        "pathname",
        "filename",
        "module",
        "exc_info",
        "exc_text",
        "stack_info",
        "lineno",
        "funcName",
        "created",
        "msecs",
        "relativeCreated",
        "thread",
        "threadName",
        "processName",
        "process",
        "taskName",
        "message",
        "asctime",
    }

    def format(self, record: logging.LogRecord) -> str:
        body = {
            "ts": datetime.fromtimestamp(record.created, tz=UTC).isoformat(),
            "level": record.levelname.lower(),
            "logger": record.name,
            "msg": record.getMessage(),
        }
        for key, value in record.__dict__.items():
            if key not in self._RESERVED and not key.startswith("_"):
                body[key] = value
        return json.dumps(body, default=str)


# -- inbound -----------------------------------------------------------


def run_inbound_loop(
    cfg: RelayConfig,
    cursor: ChatDBCursor,
    bridge: BridgeClient,
    stop: threading.Event,
) -> None:
    while not stop.is_set():
        try:
            forwarded = 0
            for msg in cursor.poll_new():
                _forward_inbound(cfg, bridge, msg)
                forwarded += 1
            if forwarded:
                logger.info("inbound_batch_forwarded", extra={"count": forwarded})
        except Exception:  # noqa: BLE001 — keep the loop alive
            logger.exception("inbound_loop_error")
        stop.wait(cfg.poll_interval_s)


def _forward_inbound(
    cfg: RelayConfig,
    bridge: BridgeClient,
    msg: InboundMessage,
) -> None:
    try:
        bridge.post_inbound(
            agent=cfg.agent_name,
            sender=msg.handle,
            body=msg.body,
            received_at=msg.received_at or _now_iso(),
            chat_guid=msg.chat_guid,
        )
    except BridgeClientError:
        logger.exception(
            "inbound_post_failed",
            extra={"rowid": msg.rowid, "chat_guid": msg.chat_guid},
        )
        # Re-raised? No — keep going. The state file has not advanced past
        # this rowid (poll_new only writes after exhaustion); a future
        # restart will re-attempt. But within this loop iteration, we
        # *have* yielded subsequent messages — the cursor's write_last_seen
        # still happens on iterator close, so we may skip retries on these.
        # Acceptable for v1; the bridge subscriber must be idempotent.


# -- outbound ----------------------------------------------------------


def run_outbound_loop(
    cfg: RelayConfig,
    bridge: BridgeClient,
    stop: threading.Event,
) -> None:
    while not stop.is_set():
        try:
            job = bridge.get_outbox(
                agent=cfg.agent_name,
                timeout_s=cfg.outbox_timeout_s,
            )
        except BridgeClientError:
            logger.exception("outbox_poll_failed")
            stop.wait(cfg.poll_interval_s)
            continue
        if job is None:
            # Long-poll timed out with empty queue; come right back.
            continue
        _dispatch_job(cfg, bridge, job)


def _dispatch_job(
    cfg: RelayConfig,
    bridge: BridgeClient,
    job: dict[str, object],
) -> None:
    message_id = str(job.get("message_id") or "")
    to = str(job.get("to") or "")
    body = str(job.get("body") or "")
    service = str(job.get("service") or "iMessage")
    if not (message_id and to and body):
        logger.warning("outbound_job_malformed", extra={"job": job})
        return
    try:
        send_imessage(to=to, body=body, service=service)
    except OsascriptError as exc:
        logger.warning(
            "outbound_send_failed",
            extra={
                "message_id": message_id,
                "code": exc.code,
                "stderr": exc.stderr,
            },
        )
        try:
            bridge.post_sent(
                agent=cfg.agent_name,
                message_id=message_id,
                to=to,
                body=body,
                status="failed",
                sent_at=_now_iso(),
                error_code=exc.code,
                error_message=exc.message,
            )
        except BridgeClientError:
            logger.exception("outbound_post_sent_failed_branch_failed")
        return

    try:
        bridge.post_sent(
            agent=cfg.agent_name,
            message_id=message_id,
            to=to,
            body=body,
            status="success",
            sent_at=_now_iso(),
        )
    except BridgeClientError:
        logger.exception(
            "outbound_post_sent_success_branch_failed",
            extra={"message_id": message_id},
        )


# -- entrypoint --------------------------------------------------------


def main() -> int:
    _setup_logging()
    try:
        cfg = RelayConfig.from_env()
    except ValueError:
        logger.exception("relay_config_invalid")
        return 2

    stop = threading.Event()

    def _handle_signal(_signum: int, _frame: FrameType | None) -> None:
        logger.info("relay_shutdown_requested")
        stop.set()

    signal.signal(signal.SIGTERM, _handle_signal)
    signal.signal(signal.SIGINT, _handle_signal)

    cursor = ChatDBCursor(cfg.chatdb_path, cfg.state_path)

    # First-run safety: if the state file doesn't exist, snapshot
    # MAX(ROWID) from chat.db and persist that as the starting point.
    # Without this the first poll cycle would treat every historical
    # message in chat.db as fresh inbound and burst them all through
    # the bridge to the brain. Idempotent — only kicks in on missing
    # state file. If chat.db isn't readable yet (FDA not granted),
    # bootstrap returns 0 and the inbound loop will retry on its
    # normal polling cadence; chat.db query errors are non-fatal.
    if not cursor.state_exists():
        cursor.bootstrap_to_tail()

    with BridgeClient(base_url=cfg.bridge_url, token=cfg.relay_token) as bridge:
        inbound = threading.Thread(
            target=run_inbound_loop,
            args=(cfg, cursor, bridge, stop),
            name="relay-inbound",
            daemon=True,
        )
        outbound = threading.Thread(
            target=run_outbound_loop,
            args=(cfg, bridge, stop),
            name="relay-outbound",
            daemon=True,
        )
        inbound.start()
        outbound.start()
        logger.info(
            "relay_started",
            extra={
                "agent": cfg.agent_name,
                "bridge_url": cfg.bridge_url,
                "chatdb": str(cfg.chatdb_path),
                "poll_interval_s": cfg.poll_interval_s,
            },
        )
        # Block on the stop event so SIGTERM unwinds cleanly.
        while not stop.is_set():
            stop.wait(timeout=1.0)
        # Give threads a moment to break out of their inner waits.
        inbound.join(timeout=cfg.poll_interval_s + 1.0)
        outbound.join(timeout=cfg.outbox_timeout_s + 1.0)
    logger.info("relay_stopped")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
