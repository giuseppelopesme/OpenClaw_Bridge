# OpenClaw

Personal AI agent ecosystem. One bridge, three brains (CLU, TRON, FLYNN), three iMessage relays. Single Mac Mini M4 host.

The bridge is the only component that talks to Apple, IMAP/SMTP, Redis, LLM providers, and the Obsidian vault. Everything else goes through it over loopback HTTP.

## Layout

```
bridge/              FastAPI app on 127.0.0.1:8788, runs as giuseppelopes
relays/imessage/     thin per-user processes (clu, tron, flynn)
brains/shared/       typed SDK consumed by every brain
brains/clu|tron|flynn/  agent processes
ops/                 launchd plists, redis config, install script
docs/                spec docs mirrored from the Obsidian vault
tools/               admin CLI
```

See [docs/repo-layout.md](docs/repo-layout.md) for boundaries and rationale.

## Spec

The spec docs are the source of truth for what the bridge must do:

- [docs/api-contract.md](docs/api-contract.md) — endpoints, auth, errors, idempotency
- [docs/event-bus.md](docs/event-bus.md) — Redis topology and topic schemas
- [docs/repo-layout.md](docs/repo-layout.md) — package boundaries
- [docs/telemetry-plan.md](docs/telemetry-plan.md) — what we instrument and why

These are mirrors of the human-authored copies in the Obsidian vault under `01 - Projects/OpenClaw/Bridge/`. Update both together.

## Tech

Python 3.13, `uv` workspace, FastAPI, redis-py async, aiosqlite, pytest + pytest-asyncio, ruff, mypy --strict on `bridge/` and `brains/shared/`. See [CLAUDE.md](CLAUDE.md) for the full convention list.

## Local dev

```bash
uv sync --group dev
./scripts/run-bridge.sh                 # serves on 127.0.0.1:8788 with JSON logs
curl -s http://127.0.0.1:8788/v1/health | jq
```

Quality gates:

```bash
uv run --no-sync pytest
uv run --no-sync ruff check .
uv run --no-sync ruff format --check .
uv run --no-sync mypy
bash scripts/check-boundaries.sh
```

`--no-sync` is a workaround for a uv 0.11.x + Python 3.13 quirk on macOS;
see `SESSION-NOTES.md`.

## Build order

1. Repo scaffold + bridge skeleton (this step) — FastAPI app, auth middleware, error envelope, `/v1/health`
2. Vault provider + `vault:read` / `vault:write`
3. LLM router + OpenRouter + `/v1/llm/complete` with telemetry
4. Redis event bus + `events:publish` / `events:subscribe`
5. Apple provider + endpoints
6. IMAP/SMTP + email endpoints
7. iMessage relay (CLU) + send/inbound endpoints
8. Brain SDK from the OpenAPI spec
9. CLU brain end-to-end
10. TRON, then FLYNN

## Status

2026-04-29 — Step 1 in progress.
