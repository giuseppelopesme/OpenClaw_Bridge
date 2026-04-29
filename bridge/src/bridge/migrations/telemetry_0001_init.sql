-- LLM call telemetry. One row per `POST /v1/llm/complete`, written after
-- the response is sent. Columns mirror `docs/telemetry-plan.md`.

CREATE TABLE IF NOT EXISTS llm_calls (
    id                 TEXT PRIMARY KEY,
    timestamp          TEXT NOT NULL,
    actor              TEXT NOT NULL,
    task_class         TEXT NOT NULL,
    provider           TEXT NOT NULL,
    model              TEXT NOT NULL,
    prompt_tokens      INTEGER NOT NULL,
    completion_tokens  INTEGER NOT NULL,
    cost_usd           REAL NOT NULL,
    latency_ms         INTEGER NOT NULL,
    status             TEXT NOT NULL,
    error_code         TEXT,
    request_id         TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_llm_calls_timestamp ON llm_calls(timestamp);
CREATE INDEX IF NOT EXISTS idx_llm_calls_task_class ON llm_calls(task_class);
CREATE INDEX IF NOT EXISTS idx_llm_calls_actor ON llm_calls(actor);
