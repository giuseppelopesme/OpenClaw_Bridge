-- agent.db schema. Tracks brain-generated drafts through the human-approval lifecycle.
--
-- One row per draft. The bridge inserts on POST /v1/agent/drafts (CLU after a
-- triage+draft pass), the operator transitions via PATCH /v1/agent/drafts/{id},
-- the bridge correlates the relay's send confirmation back to the row.
--
-- State machine (see docs/api-contract.md amendment for Session P1):
--
--   pending  --approve--> approved  --(relay sent)--> sent          (terminal-ok)
--                                  --(relay failed)-> send_failed   (retryable)
--   pending  --reject--> rejected                                   (terminal-no)
--   send_failed --approve--> approved (republishes dispatch event)
--
-- Mutations always update last_modified_at. dispatch_message_id correlates with
-- the imessage outbox (Session 7); on POST /v1/imessage/sent the bridge looks up
-- the draft by this column.

CREATE TABLE drafts (
    draft_id                  TEXT PRIMARY KEY,
    agent                     TEXT NOT NULL,
    channel                   TEXT NOT NULL,
    to_handle                 TEXT NOT NULL,
    body                      TEXT NOT NULL,
    status                    TEXT NOT NULL,
    created_at                TEXT NOT NULL,
    last_modified_at          TEXT NOT NULL,
    in_reply_to_event_id      TEXT,
    preview                   TEXT,
    approved_at               TEXT,
    approved_by               TEXT,
    reject_reason             TEXT,
    dispatch_message_id       TEXT,
    sent_at                   TEXT,
    last_send_error_code      TEXT,
    last_send_error_message   TEXT,
    publisher                 TEXT NOT NULL  -- the auth.actor of the POST /v1/agent/drafts request
);

CREATE INDEX drafts_agent_status_idx ON drafts (agent, status);
CREATE INDEX drafts_dispatch_idx     ON drafts (dispatch_message_id);
CREATE INDEX drafts_created_idx      ON drafts (created_at DESC);
