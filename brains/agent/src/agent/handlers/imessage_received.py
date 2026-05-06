"""Handler for ``imessage.received.{agent}`` envelopes.

Flow (bridge owns drafts):

1. Skip if ``state.is_processed(envelope.event_id)``.
2. Triage call (LLM, ``response_format="json"``) — returns
   ``{"action": "draft" | "ignore", "reason": "..."}``.
3. On ``ignore``: mark processed, publish
   ``agent.{agent}.task.completed`` with ``outcome="success"``, return.
4. On ``draft``: ask the LLM for a reply body, then call
   ``brains_shared.agent.create_draft`` to push the draft into the
   bridge's drafts table. The bridge auto-publishes
   ``agent.{agent}.draft.pending`` on success.
5. Publish ``agent.{agent}.task.completed`` with the right outcome.

Errors anywhere in 2–4 trip the ``except`` in this handler — we log,
mark processed (so a poison-pill message can't loop forever), and
publish ``task.completed`` with ``outcome="error"`` carrying the
exception type as the reason.
"""

from __future__ import annotations

import json
import logging
import time
from typing import Any

from brains_shared import EventEnvelope, llm, publish_event
from brains_shared.agent import create_draft

from agent.context import BrainContext

logger = logging.getLogger("agent.handlers.imessage_received")

_TRIAGE_SYSTEM = (
    "You are a personal assistant agent. Decide whether to draft a "
    "reply to the inbound iMessage shown by the user. Reply with strict "
    'JSON: {"action": "draft", "reason": "..."} or '
    '{"action": "ignore", "reason": "..."}. Choose ignore for spam, '
    "automated notifications, or messages that clearly do not require a "
    "human reply. Choose draft for everything else."
)
_DRAFT_SYSTEM = (
    "You are drafting a reply on behalf of the operator. Keep the "
    "reply concise, friendly, and in plain prose — no preamble, no "
    "sign-off, no quoting the original."
)
_PREVIEW_LEN = 80


def _now_iso() -> str:
    from datetime import UTC, datetime

    return datetime.now(UTC).isoformat()


async def handle(envelope: EventEnvelope, ctx: BrainContext) -> None:
    started = time.monotonic()
    if await ctx.state.is_processed(envelope.event_id):
        logger.info(
            "imessage_received_skipped_dedup",
            extra={"event_id": envelope.event_id},
        )
        return

    payload = envelope.payload
    sender = str(payload.get("from", ""))
    body = str(payload.get("body", ""))
    chat_guid = str(payload.get("chat_guid", ""))

    if not body:
        logger.warning(
            "imessage_received_empty_body",
            extra={"event_id": envelope.event_id, "from": sender},
        )
        await ctx.state.mark_processed(envelope.event_id, envelope.topic)
        await _publish_task_completed(
            ctx,
            event_id=envelope.event_id,
            outcome="success",
            duration_ms=_elapsed_ms(started),
        )
        return

    try:
        triage_result = await _triage(ctx, body=body, sender=sender)
        action = triage_result.get("action", "ignore")
        if action == "ignore":
            logger.info(
                "imessage_received_triage_ignore",
                extra={
                    "event_id": envelope.event_id,
                    "reason": triage_result.get("reason", ""),
                },
            )
            await ctx.state.mark_processed(envelope.event_id, envelope.topic)
            await _publish_task_completed(
                ctx,
                event_id=envelope.event_id,
                outcome="success",
                duration_ms=_elapsed_ms(started),
            )
            return

        draft_body = await _draft_reply(ctx, body=body, sender=sender)
        # Hand the draft to the bridge. The bridge stores it, publishes
        # `agent.{agent}.draft.pending`, and waits for the operator's
        # PATCH /v1/agent/drafts/{id}. The brain is purely a producer.
        created = await create_draft(
            ctx.client,
            agent=ctx.config.agent_name,
            channel="imessage",
            to_handle=sender or chat_guid,
            body=draft_body,
            in_reply_to_event_id=envelope.event_id,
            preview=draft_body[:_PREVIEW_LEN],
        )
        logger.info(
            "imessage_received_draft_created",
            extra={
                "event_id": envelope.event_id,
                "draft_id": created.draft_id,
                "to": sender,
            },
        )
        _ = chat_guid  # currently unused on the create_draft path; kept above for context

        await ctx.state.mark_processed(envelope.event_id, envelope.topic)
        await _publish_task_completed(
            ctx,
            event_id=envelope.event_id,
            outcome="success",
            duration_ms=_elapsed_ms(started),
        )
    except Exception as exc:  # noqa: BLE001 — keep the loop alive
        logger.exception(
            "imessage_received_error",
            extra={"event_id": envelope.event_id, "exc_type": type(exc).__name__},
        )
        # Poison-pill defence: mark processed even on failure so a
        # malformed envelope can't loop the loop. Subscribers must be
        # idempotent (per docs/event-bus.md); this is the cost of that
        # contract.
        try:
            await ctx.state.mark_processed(envelope.event_id, envelope.topic)
        except Exception:  # noqa: BLE001
            logger.exception("imessage_received_mark_processed_failed")
        await _publish_task_completed(
            ctx,
            event_id=envelope.event_id,
            outcome="error",
            duration_ms=_elapsed_ms(started),
            error=type(exc).__name__,
        )


# -- LLM calls --------------------------------------------------------


async def _triage(
    ctx: BrainContext,
    *,
    body: str,
    sender: str,
) -> dict[str, Any]:
    user_prompt = f"From: {sender}\n\nMessage:\n{body}"
    response = await llm.triage(
        ctx.client,
        messages=[
            {"role": "system", "content": _TRIAGE_SYSTEM},
            {"role": "user", "content": user_prompt},
        ],
        response_format="json",
        temperature=0.0,
        max_tokens=200,
    )
    return _parse_triage_json(response.content)


async def _draft_reply(
    ctx: BrainContext,
    *,
    body: str,
    sender: str,
) -> str:
    user_prompt = f"From: {sender}\n\nMessage:\n{body}\n\nWrite the reply text only."
    response = await llm.draft(
        ctx.client,
        messages=[
            {"role": "system", "content": _DRAFT_SYSTEM},
            {"role": "user", "content": user_prompt},
        ],
        temperature=0.5,
        max_tokens=400,
    )
    return response.content.strip()


def _parse_triage_json(raw: str) -> dict[str, Any]:
    """Best-effort parse of the triage LLM's JSON output.

    Models occasionally wrap JSON in ```json fences or add prose;
    we strip the fence and look for the first ``{ ... }`` block.
    """
    text = raw.strip()
    if text.startswith("```"):
        # ```json\n{...}\n```
        text = text.strip("`").lstrip("json").strip()
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        # Try to extract a JSON object from inside.
        start = text.find("{")
        end = text.rfind("}")
        if start == -1 or end == -1 or end <= start:
            return {"action": "ignore", "reason": "triage_unparseable"}
        try:
            parsed = json.loads(text[start : end + 1])
        except json.JSONDecodeError:
            return {"action": "ignore", "reason": "triage_unparseable"}
    if not isinstance(parsed, dict):
        return {"action": "ignore", "reason": "triage_unparseable"}
    action = parsed.get("action", "ignore")
    if action not in ("draft", "ignore"):
        return {"action": "ignore", "reason": "triage_unknown_action"}
    return parsed


# -- task.completed --------------------------------------------------


async def _publish_task_completed(
    ctx: BrainContext,
    *,
    event_id: str,
    outcome: str,
    duration_ms: int,
    error: str | None = None,
) -> None:
    payload: dict[str, Any] = {
        "task_id": event_id,
        "outcome": outcome,
        "duration_ms": duration_ms,
    }
    if error is not None:
        payload["error"] = error
    try:
        await publish_event(
            ctx.client,
            topic=f"agent.{ctx.config.agent_name}.task.completed",
            payload=payload,
        )
    except Exception as exc:  # noqa: BLE001 — best-effort, don't crash
        logger.warning(
            "task_completed_publish_failed",
            extra={"event_id": event_id, "exc_type": type(exc).__name__},
        )


def _elapsed_ms(started: float) -> int:
    return int((time.monotonic() - started) * 1000)


__all__ = ["handle"]
