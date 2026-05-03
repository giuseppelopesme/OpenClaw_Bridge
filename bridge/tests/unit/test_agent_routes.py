"""Agent draft endpoints — POST + GET (list/one) + PATCH lifecycle.

Tests cover:
- happy-path create + list + get
- scope rejection on each verb
- state-machine transitions (allowed + forbidden)
- PATCH→approved enqueues to the iMessage outbox + publishes draft.approved
- send-confirmation correlation (relay /sent updates the draft row)
- terminal-state guards (can't edit a sent draft, can't transition out of rejected)
- idempotent re-approve on send_failed (retry path)
- empty PATCH body returns 400
"""

from __future__ import annotations

import asyncio
import json
import sqlite3

from _support import TokenFixture
from bridge.eventbus.subscriber import EventSubscriber
from fastapi.testclient import TestClient

WRITE = {"Authorization": "Bearer dev-token-agent-write"}
READ = {"Authorization": "Bearer dev-token-agent-read"}
APPROVE = {"Authorization": "Bearer dev-token-agent-approve"}
RELAY = {"Authorization": "Bearer dev-token-imessage-relay"}


def _create_draft(
    client: TestClient,
    *,
    body: str = "Draft body for the operator to review.",
    to_handle: str = "+39 333 1234567",
) -> dict[str, object]:
    resp = client.post(
        "/v1/agent/drafts",
        json={
            "agent": "clu",
            "channel": "imessage",
            "to_handle": to_handle,
            "body": body,
            "in_reply_to_event_id": "evt-x",
        },
        headers=WRITE,
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


# -- POST -----------------------------------------------------------------


def test_create_draft_returns_201_with_id_and_status_pending(
    client: TestClient,
    tokens: list[TokenFixture],  # noqa: ARG001
) -> None:
    body = _create_draft(client)
    assert body["status"] == "pending"
    assert body["draft_id"]
    assert body["preview"]
    assert body["channel"] == "imessage"


def test_create_draft_requires_write_scope(client: TestClient) -> None:
    resp = client.post(
        "/v1/agent/drafts",
        json={"agent": "clu", "to_handle": "+39", "body": "x"},
        headers={"Authorization": "Bearer dev-token-empty"},
    )
    assert resp.status_code == 403


def test_create_draft_truncates_default_preview(
    client: TestClient,
    tokens: list[TokenFixture],  # noqa: ARG001
) -> None:
    long = "A" * 200
    body = _create_draft(client, body=long)
    # Default preview = first 80 chars.
    assert len(body["preview"]) == 80


def test_create_draft_publishes_draft_pending_event(
    client: TestClient,
    tokens: list[TokenFixture],  # noqa: ARG001
) -> None:
    redis = client.app.state.redis_client

    async def _expect_event() -> str:
        async with EventSubscriber(redis, "agent.clu.draft.pending") as sub:

            async def _post() -> None:
                await asyncio.to_thread(_create_draft, client)

            task = asyncio.create_task(_post())
            envelope = await asyncio.wait_for(anext(aiter(sub)), timeout=2.0)
            await task
            return envelope.topic

    topic = asyncio.run(_expect_event())
    assert topic == "agent.clu.draft.pending"


# -- GET list -------------------------------------------------------------


def test_list_drafts_filters_by_status(
    client: TestClient,
    tokens: list[TokenFixture],  # noqa: ARG001
) -> None:
    a = _create_draft(client, body="draft A")
    b = _create_draft(client, body="draft B")
    # Reject one to test the filter.
    resp = client.patch(
        f"/v1/agent/drafts/{b['draft_id']}",
        json={"status": "rejected", "reject_reason": "spam"},
        headers=APPROVE,
    )
    assert resp.status_code == 200

    pending = client.get("/v1/agent/drafts?agent=clu&status=pending", headers=READ)
    assert pending.status_code == 200
    pending_ids = [d["draft_id"] for d in pending.json()["drafts"]]
    assert a["draft_id"] in pending_ids
    assert b["draft_id"] not in pending_ids


def test_list_drafts_requires_read_scope(client: TestClient) -> None:
    resp = client.get("/v1/agent/drafts", headers={"Authorization": "Bearer dev-token-empty"})
    assert resp.status_code == 403


# -- GET one --------------------------------------------------------------


def test_get_draft_returns_full_body(
    client: TestClient,
    tokens: list[TokenFixture],  # noqa: ARG001
) -> None:
    a = _create_draft(client, body="hello operator")
    resp = client.get(f"/v1/agent/drafts/{a['draft_id']}", headers=READ)
    assert resp.status_code == 200
    body = resp.json()
    assert body["body"] == "hello operator"
    assert body["status"] == "pending"


def test_get_missing_draft_returns_404(
    client: TestClient,
    tokens: list[TokenFixture],  # noqa: ARG001
) -> None:
    resp = client.get("/v1/agent/drafts/nope-nope-nope", headers=READ)
    assert resp.status_code == 404


# -- PATCH lifecycle ------------------------------------------------------


def test_patch_pending_to_approved_enqueues_to_outbox(
    client: TestClient,
    tokens: list[TokenFixture],  # noqa: ARG001
) -> None:
    a = _create_draft(client, body="ready to send", to_handle="+39 444 5555555")
    resp = client.patch(
        f"/v1/agent/drafts/{a['draft_id']}",
        json={"status": "approved", "approved_by": "giuseppe"},
        headers=APPROVE,
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "approved"
    assert body["approved_by"] == "giuseppe"
    assert body["dispatch_message_id"]

    # The bridge RPUSHed the dispatch onto imessage:outbound:clu. Pop and verify.
    redis = client.app.state.redis_client

    async def _peek() -> dict[str, object] | None:
        raw = await redis.lpop("imessage:outbound:clu")
        if raw is None:
            return None
        return json.loads(raw.decode("utf-8"))

    job = asyncio.run(_peek())
    assert job is not None
    assert job["draft_id"] == a["draft_id"]
    assert job["to"] == "+39 444 5555555"
    assert job["body"] == "ready to send"
    assert job["message_id"] == body["dispatch_message_id"]


def test_patch_publishes_draft_approved_event(
    client: TestClient,
    tokens: list[TokenFixture],  # noqa: ARG001
) -> None:
    a = _create_draft(client)
    redis = client.app.state.redis_client

    async def _expect_approved() -> str:
        async with EventSubscriber(redis, "agent.clu.draft.approved") as sub:

            async def _patch() -> None:
                await asyncio.to_thread(
                    lambda: client.patch(
                        f"/v1/agent/drafts/{a['draft_id']}",
                        json={"status": "approved"},
                        headers=APPROVE,
                    ),
                )

            task = asyncio.create_task(_patch())
            envelope = await asyncio.wait_for(anext(aiter(sub)), timeout=2.0)
            await task
            return envelope.topic

    topic = asyncio.run(_expect_approved())
    assert topic == "agent.clu.draft.approved"


def test_patch_requires_approve_scope(
    client: TestClient,
    tokens: list[TokenFixture],  # noqa: ARG001
) -> None:
    a = _create_draft(client)
    # Read-only scope cannot approve.
    resp = client.patch(
        f"/v1/agent/drafts/{a['draft_id']}",
        json={"status": "approved"},
        headers=READ,
    )
    assert resp.status_code == 403


def test_patch_terminal_state_rejects_further_transitions(
    client: TestClient,
    tokens: list[TokenFixture],  # noqa: ARG001
) -> None:
    a = _create_draft(client)
    # Reject first.
    r1 = client.patch(
        f"/v1/agent/drafts/{a['draft_id']}",
        json={"status": "rejected"},
        headers=APPROVE,
    )
    assert r1.status_code == 200
    # Now try to revive — must 409.
    r2 = client.patch(
        f"/v1/agent/drafts/{a['draft_id']}",
        json={"status": "approved"},
        headers=APPROVE,
    )
    assert r2.status_code == 409
    assert r2.json()["error"]["code"] == "conflict"


def test_patch_empty_body_returns_400(
    client: TestClient,
    tokens: list[TokenFixture],  # noqa: ARG001
) -> None:
    a = _create_draft(client)
    resp = client.patch(
        f"/v1/agent/drafts/{a['draft_id']}",
        json={},
        headers=APPROVE,
    )
    assert resp.status_code == 400


def test_patch_edit_body_in_pending_state(
    client: TestClient,
    tokens: list[TokenFixture],  # noqa: ARG001
) -> None:
    a = _create_draft(client, body="original")
    resp = client.patch(
        f"/v1/agent/drafts/{a['draft_id']}",
        json={"body": "edited"},
        headers=APPROVE,
    )
    assert resp.status_code == 200
    assert resp.json()["body"] == "edited"


def test_patch_cannot_edit_body_after_sent(
    client: TestClient,
    tokens: list[TokenFixture],  # noqa: ARG001
) -> None:
    a = _create_draft(client)
    # Approve.
    approved = client.patch(
        f"/v1/agent/drafts/{a['draft_id']}",
        json={"status": "approved"},
        headers=APPROVE,
    ).json()
    # Simulate the relay confirming success.
    sent = client.post(
        "/v1/imessage/sent",
        json={
            "agent": "clu",
            "message_id": approved["dispatch_message_id"],
            "to": approved["to_handle"],
            "body": approved["body"],
            "status": "success",
            "sent_at": "2026-05-02T15:00:00+00:00",
        },
        headers=RELAY,
    )
    assert sent.status_code == 200
    # Now try to edit the body — must 409.
    resp = client.patch(
        f"/v1/agent/drafts/{a['draft_id']}",
        json={"body": "too late"},
        headers=APPROVE,
    )
    assert resp.status_code == 409


# -- correlation: relay /sent updates draft -------------------------------


def test_send_success_correlates_back_to_draft(
    client: TestClient,
    tokens: list[TokenFixture],  # noqa: ARG001
) -> None:
    a = _create_draft(client)
    approved = client.patch(
        f"/v1/agent/drafts/{a['draft_id']}",
        json={"status": "approved"},
        headers=APPROVE,
    ).json()
    sent = client.post(
        "/v1/imessage/sent",
        json={
            "agent": "clu",
            "message_id": approved["dispatch_message_id"],
            "to": approved["to_handle"],
            "body": approved["body"],
            "status": "success",
            "sent_at": "2026-05-02T15:00:00+00:00",
        },
        headers=RELAY,
    )
    assert sent.status_code == 200
    # Re-fetch the draft.
    final = client.get(f"/v1/agent/drafts/{a['draft_id']}", headers=READ).json()
    assert final["status"] == "sent"
    assert final["sent_at"] == "2026-05-02T15:00:00+00:00"


def test_send_failure_marks_draft_send_failed_and_retry_works(
    client: TestClient,
    tokens: list[TokenFixture],  # noqa: ARG001
) -> None:
    a = _create_draft(client)
    approved = client.patch(
        f"/v1/agent/drafts/{a['draft_id']}",
        json={"status": "approved"},
        headers=APPROVE,
    ).json()
    # Relay reports failure.
    fail = client.post(
        "/v1/imessage/sent",
        json={
            "agent": "clu",
            "message_id": approved["dispatch_message_id"],
            "to": approved["to_handle"],
            "body": approved["body"],
            "status": "failed",
            "error_code": "buddy_not_found",
            "error_message": "not on iMessage",
        },
        headers=RELAY,
    )
    assert fail.status_code == 200
    after_fail = client.get(f"/v1/agent/drafts/{a['draft_id']}", headers=READ).json()
    assert after_fail["status"] == "send_failed"
    assert after_fail["last_send_error_code"] == "buddy_not_found"

    # Retry by re-approving — must succeed and clear the error markers.
    retried = client.patch(
        f"/v1/agent/drafts/{a['draft_id']}",
        json={"status": "approved"},
        headers=APPROVE,
    ).json()
    assert retried["status"] == "approved"
    assert retried["last_send_error_code"] is None
    assert retried["dispatch_message_id"] != approved["dispatch_message_id"]


def test_send_unknown_message_id_does_not_break_route(
    client: TestClient,
    tokens: list[TokenFixture],  # noqa: ARG001
) -> None:
    """A relay /sent with a message_id that doesn't match any draft must
    not 5xx — it might be a non-draft direct send via /v1/imessage/send."""
    resp = client.post(
        "/v1/imessage/sent",
        json={
            "agent": "clu",
            "message_id": "00000000-0000-0000-0000-000000000000",
            "to": "+39",
            "body": "x",
            "status": "success",
        },
        headers=RELAY,
    )
    assert resp.status_code == 200


# -- agent_db down --------------------------------------------------------


def test_agent_db_unavailable_returns_502(
    client: TestClient,
    tokens: list[TokenFixture],  # noqa: ARG001
) -> None:
    client.app.state.agent_conn = None
    resp = client.post(
        "/v1/agent/drafts",
        json={"agent": "clu", "to_handle": "+39", "body": "x"},
        headers=WRITE,
    )
    assert resp.status_code == 502
    assert resp.json()["error"]["code"] == "dependency_unavailable"


# -- direct correlation function ------------------------------------------


def test_correlate_send_outcome_returns_none_for_missing_draft(
    tmp_path,  # noqa: ANN001
) -> None:
    """Direct unit test on the correlate helper for the unmatched-id path."""
    from bridge.migrations import open_with_migrations
    from bridge.routes.agent import correlate_send_outcome

    conn: sqlite3.Connection = open_with_migrations(tmp_path / "agent.db", prefix="agent")
    try:
        result = correlate_send_outcome(
            conn,
            dispatch_message_id="00000000-0000-0000-0000-000000000000",
            status="success",
            sent_at="2026-05-02T15:00:00+00:00",
            error_code=None,
            error_message=None,
        )
        assert result is None
    finally:
        conn.close()
