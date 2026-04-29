---
created: 2026-04-29
source: claude-conversation
topic: bridge telemetry and local-LLM decision frame
status: active
---

# Telemetry Plan

The goal is narrow: have enough data after two weeks of CLU running to decide rationally whether to install a local LLM, what size, and for which task classes. Without this data the decision is vibes.

## What we record

Every `POST /v1/llm/complete` call writes one row to a SQLite database at `/Users/giuseppelopes/.openclaw/telemetry.db`. The bridge owns this file; brains never touch it directly.

| field | type | notes |
|---|---|---|
| `id` | uuid | primary key |
| `timestamp` | iso8601 | UTC |
| `actor` | text | `brain.clu`, `brain.tron`, `brain.flynn`, `cli.giuseppelopes` |
| `task_class` | text | `triage`, `classify`, `reason`, `draft`, `summarise` |
| `provider` | text | `openrouter`, `local` |
| `model` | text | full model id (e.g. `anthropic/claude-haiku-4.5`) |
| `prompt_tokens` | integer | |
| `completion_tokens` | integer | |
| `cost_usd` | real | computed at write time using a price table per (provider, model) |
| `latency_ms` | integer | end-to-end at the bridge, including network |
| `status` | text | `success`, `error`, `timeout` |
| `error_code` | text | nullable |
| `request_id` | uuid | links to the bridge access log |

Schema migrations live in `bridge/migrations/` and run on bridge startup.

## Bridge access log

Separate JSONL file at `/Users/giuseppelopes/.openclaw/access.log`, rotated daily, retained 30 days. One line per HTTP request to the bridge:

```json
{"ts":"2026-04-29T10:00:00Z","request_id":"...","method":"POST","path":"/v1/llm/complete","scope_used":"llm:call","actor":"brain.clu","status":200,"duration_ms":1234,"idempotency_replay":false}
```

Used for incident debugging, not analysis. The telemetry DB is the analysis surface.

## Decision frame for local LLM (T+14 days)

After two weeks of real CLU usage, run the analysis script at `tools/analyse-telemetry.py` which produces:

1. **Total run-rate**: monthly cost projection at OpenRouter, in USD and EUR
2. **Cost distribution by task_class**: percentage of total cost spent on each class
3. **Token volume by task_class**: total prompt + completion tokens per class
4. **Latency distribution by task_class**: p50, p95, p99
5. **Failure rate by task_class**: error and timeout counts

### The trigger thresholds

Install a local model if any one of these holds:

- `triage + classify` cost share ≥ 30% of total monthly spend, AND total monthly spend ≥ €30. Below €30, the operational complexity of a local model isn't worth it regardless of share.
- p95 latency on `triage` exceeds 2 seconds and triage volume is ≥ 100 calls/day. The agents *feel slow* if triage is slow.
- Any task class shows ≥ 5% timeout rate against OpenRouter — local fallback becomes a reliability win, not just a cost one.

### What model to install

Constrained by the M4's unified memory after macOS, daily-driver apps, bridge, Redis, and three agent brains. Realistic budget: 5–6 GB for a model.

- If triage volume dominates and latency matters → Llama 3.2 3B Q4 (~2 GB), very fast, sufficient for classification and routing.
- If we also want richer triage (entity extraction, intent inference) → Qwen 2.5 7B Instruct Q4_K_M (~4.7 GB), strong general capability for the size.
- Anything ≥14B is off the table on this hardware while running the full stack.

Whatever we pick, it gets wired in as the `local` provider in the LLM router — no new code in the brains. They keep calling `/v1/llm/complete` with `task_class`. The router does the work.

## Reporting cadence

The analysis script can run on demand. After the T+14 review, schedule it weekly on Sundays at 22:00 via launchd, with a summary published to `agent.system.telemetry.weekly` and written to `04 - Daily/YYYY-MM-DD - OpenClaw telemetry.md` in the vault.
