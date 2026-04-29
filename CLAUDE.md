# OpenClaw

Personal AI agent ecosystem. One bridge, three brains (CLU, TRON, FLYNN), three iMessage relays. Single Mac Mini M4 host.

## Status

Greenfield. Mac Mini was wiped, fresh macOS 26.4.1, nothing installed. Spec is written; code starts now.

## Architecture in brief

- `bridge/` — FastAPI on `127.0.0.1:8788`, runs as `giuseppelopes`. The only component that talks to Apple, IMAP/SMTP, Redis, LLM providers, vault.
- `relays/imessage/` — thin processes (~200 LOC each) running as `clu`, `tron`, `flynn` macOS users. Poll `chat.db`, send via osascript, talk to the bridge over loopback. Nothing else.
- `brains/{clu,tron,flynn}/` — agent processes running as `giuseppelopes`. Talk only to the bridge via the typed `brains/shared` SDK. Never to each other directly.
- Event bus: Redis pub/sub on `127.0.0.1:6379`, mediated exclusively by the bridge.

## Source of truth

The spec lives in the Obsidian vault at `01 - Projects/OpenClaw/Bridge/`:

- `API Contract v1.md`
- `Event Bus.md`
- `Repo Layout.md`
- `Telemetry Plan.md`

Mirror these into `docs/` in the repo as identical markdown. Vault copies are the human source; `docs/` makes the repo self-contained. Update both together — never one without the other.

## Tech stack (locked)

- Python 3.13
- `uv` for env and lockfile management; workspace at repo root
- FastAPI for the bridge HTTP layer
- `redis-py` async
- `aiosqlite` for telemetry
- `pytest` + `pytest-asyncio`
- `ruff` for lint and format
- `mypy --strict` on `bridge/` and `brains/shared/` from day one

Adding a dependency not in this list requires a conversation first.

## Conventions

- Cross-package imports are forbidden except `brains/*` → `brains/shared`. Enforce in CI.
- Every endpoint ships with at least one happy-path test and one error-path test before it's considered done.
- Every error response uses the envelope from API Contract v1. No exceptions.
- Structured JSON logs to stderr. No `print()`.
- No bare `except:`. Catch the narrowest exception that fits.
- Type-annotate everything, including private helpers.
- New endpoints go in `bridge/src/bridge/routes/<domain>.py` and register in `main.py`. No god-route file.
- Commit small, commit often. Each commit is a green test run.

## Build order (locked)

Each step is independently testable and shippable. Don't reorder without a conversation.

1. Repo scaffold + bridge skeleton (FastAPI app, auth middleware, error envelope, `/v1/health`)
2. Vault provider + `vault:read` / `vault:write` endpoints
3. LLM router + OpenRouter provider + `/v1/llm/complete` with telemetry recording
4. Redis event bus + `events:publish` / `events:subscribe`
5. Apple provider (calendar, reminders, contacts) + endpoints
6. IMAP/SMTP provider + email endpoints
7. iMessage relay (CLU only) + `imessage:send` / `imessage:inbound`
8. Brain SDK (`brains/shared`) generated from the OpenAPI spec
9. CLU brain — first event subscriber, full end-to-end loop
10. TRON, then FLYNN

The bridge is useful at step 4. CLU is end-to-end at step 9. TRON and FLYNN come after the pattern is proven.

## Stop and ask before

- Adding a dependency not in the stack above
- Changing the API contract (vault docs are authoritative; we update them together)
- Touching anything under `06 - Archive/` in the vault
- Modifying or installing launchd plists for the first time
- Storing real secrets anywhere outside macOS Keychain

## Working principles

- Direct and concise. No preamble.
- When unclear, ask once, then proceed.
- Decisions and frameworks beat raw detail.
- If a yes/no question is asked, lead with the answer.
