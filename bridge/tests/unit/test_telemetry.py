"""Telemetry: write_llm_call writes a row; access log emits JSONL lines.

The route uses FastAPI BackgroundTasks to run the write after the response is
sent, but the underlying call is synchronous — see the LLM route tests for
end-to-end coverage of that flow.
"""

from __future__ import annotations

import json
import logging
import sqlite3
from collections.abc import Iterator
from pathlib import Path

import pytest
from bridge.migrations import open_with_migrations
from bridge.telemetry import (
    LLMCallRecord,
    setup_access_log,
    write_llm_call,
)


@pytest.fixture
def tele_conn(tmp_path: Path) -> Iterator[sqlite3.Connection]:
    conn = open_with_migrations(tmp_path / "telemetry.db", prefix="telemetry")
    try:
        yield conn
    finally:
        conn.close()


def _record(**overrides: object) -> LLMCallRecord:
    base: dict[str, object] = {
        "actor": "brain.agent",
        "task_class": "triage",
        "provider": "openrouter",
        "model": "anthropic/claude-haiku-4.5",
        "prompt_tokens": 10,
        "completion_tokens": 5,
        "cost_usd": 0.000035,
        "latency_ms": 42,
        "status": "success",
        "request_id": "req-1",
        "error_code": None,
    }
    base.update(overrides)
    return LLMCallRecord(**base)  # type: ignore[arg-type]


def test_write_persists_row(tele_conn: sqlite3.Connection) -> None:
    write_llm_call(tele_conn, _record())
    rows = tele_conn.execute("SELECT actor, status, request_id FROM llm_calls").fetchall()
    assert rows == [("brain.agent", "success", "req-1")]


def test_write_with_error_code(tele_conn: sqlite3.Connection) -> None:
    write_llm_call(tele_conn, _record(status="error", error_code="dependency_unavailable"))
    status, code = tele_conn.execute(
        "SELECT status, error_code FROM llm_calls",
    ).fetchone()
    assert status == "error"
    assert code == "dependency_unavailable"


def test_write_failure_is_swallowed(caplog: pytest.LogCaptureFixture) -> None:
    """Closed connection -> sqlite error -> swallowed, logged, no raise."""
    conn = sqlite3.connect(":memory:")
    conn.close()

    with caplog.at_level(logging.ERROR, logger="bridge.telemetry"):
        write_llm_call(conn, _record())  # must not raise
    assert any("telemetry_write_failed" in rec.message for rec in caplog.records)


def test_setup_access_log_writes_jsonl(tmp_path: Path) -> None:
    log_path = tmp_path / "access.log"
    handler = setup_access_log(log_path)
    try:
        logger = logging.getLogger("bridge.access")
        logger.info(
            "request",
            extra={
                "request_id": "rid-1",
                "method": "GET",
                "path": "/v1/health",
                "status": 200,
                "duration_ms": 7,
                "actor": None,
            },
        )
        handler.flush()
    finally:
        logger.removeHandler(handler)
        handler.close()

    raw = log_path.read_text(encoding="utf-8").strip()
    assert raw, "expected a JSONL line in the access log"
    body = json.loads(raw)
    assert body["request_id"] == "rid-1"
    assert body["method"] == "GET"
    assert body["path"] == "/v1/health"
    assert body["status"] == 200
    assert body["duration_ms"] == 7
    assert body["actor"] is None
    assert "ts" in body


def test_setup_access_log_is_idempotent(tmp_path: Path) -> None:
    """Calling setup twice on the same path must not double-attach handlers."""
    h1 = setup_access_log(tmp_path / "access.log")
    h2 = setup_access_log(tmp_path / "access.log")
    try:
        assert h1 is h2
        logger = logging.getLogger("bridge.access")
        rotating = [
            h for h in logger.handlers if h.__class__.__name__ == "TimedRotatingFileHandler"
        ]
        assert len(rotating) == 1
    finally:
        logger.removeHandler(h1)
        h1.close()
