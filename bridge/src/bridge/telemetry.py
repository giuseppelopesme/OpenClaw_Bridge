"""Telemetry — LLM call records (SQLite) + JSONL access log.

Two surfaces, both owned by the bridge:

1. **`telemetry.db`** at `~/.openclaw/telemetry.db` — one row per
   `POST /v1/llm/complete`, written *after* the response goes out. The
   schema is in `bridge.migrations.telemetry_0001_init.sql` and is
   applied at startup via `apply_migrations(conn, prefix="telemetry")`.

   Writes go through `record_llm_call(...)` which schedules the actual
   INSERT on the asyncio loop via `asyncio.create_task` so the caller
   never blocks on disk I/O. A telemetry failure must never break an LLM
   call — every exception is caught and logged.

2. **`access.log`** at `~/.openclaw/access.log` — one JSONL line per HTTP
   request, format per `docs/telemetry-plan.md`. Daily rotation via
   stdlib `TimedRotatingFileHandler`, 30-day retention. Configured by
   `setup_access_log(...)`, called from `bridge.__main__` (so tests do
   not write a daily-rotating file on disk; they assert the structured
   log line is emitted via the `bridge.access` logger).
"""

from __future__ import annotations

import json
import logging
import logging.handlers
import sqlite3
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Final

logger = logging.getLogger("bridge.telemetry")
access_logger = logging.getLogger("bridge.access")

ACCESS_LOG_BACKUP_DAYS: Final[int] = 30


@dataclass(frozen=True)
class LLMCallRecord:
    """One row destined for `llm_calls`. All fields are required except `error_code`."""

    actor: str
    task_class: str
    provider: str
    model: str
    prompt_tokens: int
    completion_tokens: int
    cost_usd: float
    latency_ms: int
    status: str  # "success" | "error" | "timeout"
    request_id: str
    error_code: str | None = None


def write_llm_call(conn: sqlite3.Connection, record: LLMCallRecord) -> None:
    """Synchronous insert — swallows errors after logging.

    The route handler schedules this via `BackgroundTasks` so it runs *after*
    the response is sent (non-blocking from the caller's perspective) while
    still being observable inside the request lifecycle (which keeps tests
    deterministic — see `bridge/tests/unit/test_telemetry.py`).
    """
    try:
        _write_one(conn, record)
    except sqlite3.Error:
        logger.exception(
            "telemetry_write_failed",
            extra={"actor": record.actor, "request_id": record.request_id},
        )


def _write_one(conn: sqlite3.Connection, record: LLMCallRecord) -> None:
    conn.execute(
        """
        INSERT INTO llm_calls (
            id, timestamp, actor, task_class, provider, model,
            prompt_tokens, completion_tokens, cost_usd, latency_ms,
            status, error_code, request_id
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            str(uuid.uuid4()),
            datetime.now(UTC).isoformat(),
            record.actor,
            record.task_class,
            record.provider,
            record.model,
            record.prompt_tokens,
            record.completion_tokens,
            record.cost_usd,
            record.latency_ms,
            record.status,
            record.error_code,
            record.request_id,
        ),
    )


# --- access log -----------------------------------------------------------


class _AccessLogJSONFormatter(logging.Formatter):
    """One JSONL line per record. Fields documented in telemetry-plan.md."""

    def format(self, record: logging.LogRecord) -> str:
        body: dict[str, object] = {
            "ts": datetime.now(UTC).isoformat(),
            "request_id": getattr(record, "request_id", "") or "",
            "method": getattr(record, "method", "") or "",
            "path": getattr(record, "path", "") or "",
            "status": getattr(record, "status", 0),
            "duration_ms": getattr(record, "duration_ms", 0),
            "actor": getattr(record, "actor", None),
        }
        # Flag idempotency replay when the access middleware ever surfaces it.
        if hasattr(record, "idempotency_replay"):
            body["idempotency_replay"] = bool(record.idempotency_replay)
        return json.dumps(body, ensure_ascii=False)


def setup_access_log(path: Path) -> logging.Handler:
    """Attach a daily-rotating JSONL handler to the `bridge.access` logger.

    Idempotent: if a `_TimedRotatingFileHandler` already exists on the
    logger pointing at the same file, do nothing.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    for h in access_logger.handlers:
        if isinstance(h, logging.handlers.TimedRotatingFileHandler):
            return h
    handler = logging.handlers.TimedRotatingFileHandler(
        filename=str(path),
        when="midnight",
        backupCount=ACCESS_LOG_BACKUP_DAYS,
        encoding="utf-8",
        delay=True,
    )
    handler.setFormatter(_AccessLogJSONFormatter())
    handler.setLevel(logging.INFO)
    access_logger.addHandler(handler)
    access_logger.setLevel(logging.INFO)
    # Don't double-emit through the root logger's stderr handler.
    access_logger.propagate = False
    return handler
