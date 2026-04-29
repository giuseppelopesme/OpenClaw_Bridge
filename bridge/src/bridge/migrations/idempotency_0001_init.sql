-- Idempotency-key cache. One row per Idempotency-Key seen on a POST request.
--
-- `body_hash` is sha256 of the raw request body, hex-encoded.
-- `headers` is a JSON list of [name, value] pairs from the cached response,
-- excluding hop-by-hop and per-response framing headers (Content-Length is
-- recomputed at replay).
--
-- TTL is 24h; expired rows are pruned lazily during lookup.

CREATE TABLE IF NOT EXISTS idempotency (
    key         TEXT PRIMARY KEY,
    body_hash   TEXT NOT NULL,
    status      INTEGER NOT NULL,
    headers     TEXT NOT NULL,
    body        BLOB NOT NULL,
    created_at  INTEGER NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_idempotency_created_at
    ON idempotency(created_at);
