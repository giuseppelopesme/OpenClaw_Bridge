# OpenClaw

Personal-AI bridge for macOS. One bridge, one configurable brain, one
iMessage relay. Single Mac Mini host.

The bridge is the only component that talks to Apple, IMAP/SMTP,
Redis, LLM providers, and the Obsidian vault. Everything else goes
through it over loopback HTTP.

## Layout

```
bridge/              FastAPI app on 127.0.0.1:8788, runs as the operator
relays/imessage/     thin per-account process (account-agnostic)
brains/shared/       typed SDK consumed by the brain
brains/agent/        the brain process (default agent identity)
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

These are mirrors of the human-authored copies in the Obsidian vault
under `01 - Projects/OpenClaw/Bridge/`. Update both together.

## Tech

Python 3.13, `uv` workspace, FastAPI, redis-py async, sqlite3,
pytest + pytest-asyncio, ruff, mypy --strict on `bridge/` and
`brains/shared/`. See [CLAUDE.md](CLAUDE.md) for the full convention
list.

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

`--no-sync` is a workaround for a uv 0.11.x + Python 3.13 quirk on macOS.

## Production install

The signed + notarized `MacOSBridgeForOpenClaw.pkg` is the canonical
install path. It drops both `OpenClawBridge.app` and
`OpenClawRelay.app` into `/Applications/`, picks the iMessage relay's
service-user account via an osascript dialog, and registers both
LaunchAgents via `SMAppService.agent(plistName:)` in the right
per-user Aqua sessions. See `installer/README.md`.
