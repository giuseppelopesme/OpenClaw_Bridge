---
created: 2026-04-29
source: claude-conversation
topic: bridge event bus
status: active
---

# Event Bus

Redis-backed pub/sub mediated by the bridge. No component talks to Redis directly. The bridge is the only component with the Redis password.

## Topology

Single Redis instance on `127.0.0.1:6379`. Configuration:

```
bind 127.0.0.1
port 6379
requirepass <generated-on-install>
appendonly no
save ""
maxmemory 256mb
maxmemory-policy allkeys-lru
```

Pub/sub is ephemeral — no persistence in v1. Stream-based persistent events get added if and when we need replay.

## Topic naming

Hierarchical, dot-separated: `<domain>.<event>.<scope>`.

Domains in v1: `imessage`, `mail`, `calendar`, `vault`, `agent`, `system`. Subscribers can pattern-match with `*` at any segment, e.g. `imessage.received.*` or `agent.tron.*`.

## Envelope

Every event is a JSON object with this envelope. Subscribers should validate `schema_version` before parsing `payload`.

```json
{
  "event_id": "uuid",
  "topic": "imessage.received.clu",
  "published_at": "2026-04-29T10:00:00Z",
  "publisher": "relay.clu",
  "schema_version": "1",
  "payload": { ... topic-specific ... }
}
```

## Initial topic catalogue

| topic | publisher | payload |
|---|---|---|
| `imessage.received.{agent}` | relay | `{ from, body, chat_guid, received_at }` |
| `imessage.sent.{agent}` | bridge | `{ to, body, message_id, sent_at }` |
| `imessage.send.failed.{agent}` | bridge | `{ to, body, error_code, error_message, attempted_at }` |
| `mail.received.{account}` | mail watcher | `{ from, subject, snippet, message_id, received_at, account }` |
| `calendar.event.upcoming` | scheduler | `{ event_id, title, start, minutes_until }` |
| `calendar.event.starting` | scheduler | `{ event_id, title, start }` |
| `vault.changed` | fswatch | `{ path, op: "create\|modify\|delete", changed_at }` |
| `agent.{name}.thinking` | brain | `{ task_id, started_at, task_class }` |
| `agent.{name}.task.completed` | brain | `{ task_id, outcome: "success\|error", duration_ms }` |
| `agent.{name}.draft.pending` | brain | `{ draft_id, channel: "linkedin\|x\|email\|imessage", preview }` |
| `agent.{name}.draft.approved` | brain | `{ draft_id, approved_by, approved_at }` |
| `system.bridge.startup` | bridge | `{ version, started_at }` |
| `system.dependency.degraded` | bridge | `{ dep, status, since }` |

New topics get added when needed. Schema is versioned per topic via the envelope.

## Patterns to follow

- Publish events for state changes worth subscribing to. Don't publish for internal bridge plumbing.
- Payloads are small. If you need to attach a large blob (full email body, full draft text), publish the metadata and an opaque ID; subscribers fetch via the bridge.
- Every event is fire-and-forget. Subscribers must be idempotent — replays are possible if a subscriber reconnects mid-stream.
- Topic hierarchies stay shallow. Three segments is the norm; four is the limit.
