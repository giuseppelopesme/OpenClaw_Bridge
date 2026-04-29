---
created: 2026-04-29
source: claude-conversation
topic: openclaw monorepo layout
status: active
last_revised: 2026-04-29
---

# Repo Layout

Single Git repository: `giuseppelopesme/OpenClaw_Bridge` on private GitHub. Mono-repo with three first-class concerns — bridge, relays, brains — and a shared SDK package consumed by the brains. Local checkout lives at `~/Developer/OpenClaw_Bridge` on the Mac Mini. Do not put the working tree inside iCloud Drive — it produces sync-conflict copies of `uv.lock` and other live files; for cross-machine sync use the GitHub remote.

## Tree

```
OpenClaw_Bridge/
├── README.md
├── pyproject.toml              # workspace root, declares packages
├── uv.lock                     # uv for env management
├── .env.example
├── .gitignore
├── .github/workflows/
│   ├── ci.yml                  # ruff + mypy + pytest matrix per package
│   └── release.yml
├── docs/
│   ├── api-contract.md         # mirrors Obsidian; vault is source of truth
│   ├── event-bus.md
│   ├── repo-layout.md
│   ├── telemetry-plan.md
│   ├── openapi-v1.yaml         # generated from FastAPI app (gitignored until step 8)
│   └── runbooks/
│       ├── bridge-restart.md
│       ├── relay-recovery.md
│       └── token-rotation.md
├── bridge/
│   ├── pyproject.toml
│   ├── src/bridge/
│   │   ├── __init__.py
│   │   ├── main.py             # FastAPI app entry, create_app() factory
│   │   ├── __main__.py         # `python -m bridge` entrypoint with JSON logging
│   │   ├── config.py           # env + keychain loading
│   │   ├── auth.py             # token validation, scope check
│   │   ├── errors.py           # error envelope, exception handlers
│   │   ├── middleware.py       # plain ASGI: RequestID + AccessLog
│   │   ├── logging_setup.py
│   │   ├── idempotency.py      # idempotency-key middleware
│   │   ├── ratelimit.py        # token bucket
│   │   ├── telemetry.py        # SQLite writer + access log
│   │   ├── routes/
│   │   │   ├── health.py
│   │   │   ├── auth.py
│   │   │   ├── imessage.py
│   │   │   ├── calendar.py
│   │   │   ├── reminders.py
│   │   │   ├── contacts.py
│   │   │   ├── email.py
│   │   │   ├── vault.py
│   │   │   ├── llm.py
│   │   │   └── events.py
│   │   ├── providers/
│   │   │   ├── apple/
│   │   │   │   ├── calendar.py
│   │   │   │   ├── reminders.py
│   │   │   │   └── contacts.py # EventKit / AppleScript
│   │   │   ├── email/
│   │   │   │   ├── imap.py
│   │   │   │   └── smtp.py
│   │   │   ├── llm/
│   │   │   │   ├── base.py     # protocol
│   │   │   │   ├── openrouter.py
│   │   │   │   ├── local.py    # plug for future local model
│   │   │   │   └── router.py   # task_class → provider
│   │   │   └── vault.py        # filesystem reads/writes against Obsidian path
│   │   └── eventbus/
│   │       ├── publisher.py
│   │       └── subscriber.py
│   ├── tests/
│   │   ├── unit/
│   │   └── integration/
│   └── README.md
├── relays/
│   └── imessage/
│       ├── pyproject.toml
│       ├── src/relay/
│       │   ├── __init__.py
│       │   ├── main.py         # poll loop + send queue consumer
│       │   ├── chatdb.py       # read-only sqlite cursor on chat.db
│       │   ├── osascript.py    # send via Messages.app
│       │   ├── bridge_client.py
│       │   └── config.py
│       └── tests/
├── brains/
│   ├── shared/
│   │   ├── pyproject.toml
│   │   └── src/brains_shared/
│   │       ├── client.py       # typed bridge SDK, generated from openapi
│   │       ├── eventbus.py     # WebSocket subscriber helper
│   │       ├── obsidian.py     # vault-write helpers
│   │       └── llm.py          # task_class shortcuts
│   ├── clu/
│   │   ├── pyproject.toml
│   │   └── src/clu/
│   │       ├── main.py
│   │       ├── handlers/       # one per event type subscribed to
│   │       └── config.py
│   ├── tron/
│   │   └── …
│   └── flynn/
│       └── …
├── ops/
│   ├── launchd/
│   │   ├── com.giuseppelopesme.openclaw.bridge.plist
│   │   ├── com.giuseppelopesme.openclaw.redis.plist
│   │   ├── com.giuseppelopesme.openclaw.relay.clu.plist
│   │   ├── com.giuseppelopesme.openclaw.relay.tron.plist
│   │   ├── com.giuseppelopesme.openclaw.relay.flynn.plist
│   │   └── com.giuseppelopesme.openclaw.brain.clu.plist
│   ├── redis/redis.conf
│   └── install.sh              # bootstraps from a fresh macOS
├── scripts/
│   ├── run-bridge.sh           # canonical bridge launcher (see Operational notes)
│   ├── check-boundaries.sh     # package-boundary enforcement
│   ├── mint-token.py
│   ├── rotate-token.py
│   └── health-check.sh
└── tools/
    ├── claw                    # admin CLI (mint tokens, tail events, replay)
    └── claw-tui                # optional curses dashboard
```

## Naming convention

The reverse-DNS namespace for everything OpenClaw — Keychain service identifiers, launchd plist labels, anything else macOS expects in this form — is `com.giuseppelopesme.openclaw.<component>`. It matches the GitHub username (`giuseppelopesme`) for visual consistency. OpenClaw is personal infrastructure; it has no organisational owner. Do not introduce alternative namespaces (Glysk OÜ runs on the platform but does not own it).

## Package boundaries

The boundaries below are enforced by `scripts/check-boundaries.sh` — a grep-based check that runs in pre-commit and CI. Ruff's `flake8-tidy-imports` cannot express directory-scoped allow-lists, which is what these rules require, so the shell script is the canonical enforcer. It is trivially extensible.

- `bridge` knows about Apple, email, vault, Redis, and LLM providers. Speaks no agent logic. Never imports from `relays/` or `brains/`.
- `relays/imessage` knows only `chat.db` and AppleScript. Talks to the bridge over HTTP using a thin client. Never imports from `bridge/` or `brains/`.
- `brains/shared` is the typed SDK every brain uses to call the bridge. Generated from the OpenAPI spec. Never imports from `bridge/` (it consumes the spec, not the code).
- `brains/{name}` knows only its own logic and `brains_shared`. Never imports from `bridge/` or `relays/`.

The point is brutal: if Tron's brain breaks, it cannot bring down the bridge or CLU's relay. If a relay crashes, the bridge keeps serving. If the bridge restarts, relays and brains reconnect cleanly.

## Tooling

- Python 3.13, `uv` for env and lockfile management
- Build backend: `uv_build` (natural fit for a uv-managed workspace, one fewer dep in the lockfile)
- `ruff` for lint + format (replaces black + isort + flake8). Configured at workspace root: line-length 100, broad rule selection including `ANN`, `BLE`, `T20`.
- `mypy --strict` on `bridge/` and `brains/shared/`. Brains and relays start at `--strict` from day one — easier than retrofitting.
- `pytest` + `pytest-asyncio`. Workspace `pyproject.toml` sets `[tool.pytest.ini_options].pythonpath` to each member's `src/` and `filterwarnings = ["error"]` so deprecation warnings break the build instead of accumulating.
- Pre-commit hooks: ruff check, ruff format check, mypy, `scripts/check-boundaries.sh` on every commit; pytest on push. All hooks invoke `uv run --no-sync` (see Operational notes).
- CI on GitHub Actions, matrix per package, integration tests against a Redis service container.

## Operational notes

### Canonical bridge launcher

`./scripts/run-bridge.sh` is the production launcher. It exports `PYTHONPATH` to the workspace `src/` directories explicitly and execs `python -m bridge` with JSON logging configured. Use this — not `uv run uvicorn bridge.main:app` — for any non-trivial run.

Reason: uv 0.11.8 generates editable workspace `.pth` files with the macOS `UF_HIDDEN` flag set, and Python 3.13's `site.py` skips hidden `.pth` files (`st.st_flags & stat.UF_HIDDEN` check in `site.addpackage`). The result: workspace packages drop off `sys.path` non-deterministically, often after a re-sync. `uv run uvicorn …` works after a fresh `uv sync` but cannot be relied on across repeated invocations.

### `uv run --no-sync` everywhere

All automation (CI, pre-commit, launcher) invokes `uv run --no-sync …`. The pattern is:

- `uv sync --group dev` once per environment (CI step, fresh dev checkout)
- `uv run --no-sync …` for everything that follows

This avoids uv re-applying `UF_HIDDEN` on every invocation and the partially-broken venv states that produces.

### Removing the workaround

When uv ships a fix for the hidden-`.pth` interaction, the cleanup is mechanical:

1. Drop `--no-sync` from CI workflows, pre-commit hooks, and `scripts/run-bridge.sh`
2. Remove `pythonpath` from `[tool.pytest.ini_options]` in the root `pyproject.toml`
3. Remove the `PYTHONPATH` export from `scripts/run-bridge.sh`
4. Delete this section

Every workaround site carries an explicit `# uv 0.11.8 hidden-pth workaround` comment so they're easy to find with `grep -r`.

## Bootstrap

`ops/install.sh` runs from a fresh macOS and is itself versioned. Steps:

1. Create `clu`, `tron`, `flynn` users (idempotent)
2. Install Homebrew, Python 3.13, Redis, `uv`
3. Clone the repo to `~/Developer/OpenClaw_Bridge`
4. Generate Redis password and bridge token salt, store in macOS Keychain under service `com.giuseppelopesme.openclaw.bridge`
5. Mint initial tokens for each component
6. Install launchd plists (bridge → redis → relays → brains, in dependency order)
7. Run health check

The whole bootstrap should be reproducible end-to-end in under 10 minutes on the M4.

---

## Changelog — 2026-04-29 (Session 1 deviations + namespace cleanup)

Folded into the body above. Listed here for traceability against the original spec.

- **Repo location**: `~/Developer/OpenClaw_Bridge` (was `~/openclaw`). Repo briefly lived inside iCloud Drive and was moved out after sync conflicts created duplicate `uv.lock` copies.
- **Namespace**: `com.giuseppelopesme.openclaw.*` (was `com.glysk.openclaw.*`). OpenClaw is personal infrastructure with no organisational owner. Affects Keychain service identifier, six launchd plist filenames, and the GitHub repo path (now `giuseppelopesme/OpenClaw_Bridge`).
- **Boundary enforcement**: `scripts/check-boundaries.sh` (was "ruff + custom rule" — ruff cannot express what the rule actually requires).
- **Canonical launcher**: `./scripts/run-bridge.sh` (was `uv run uvicorn …`); workaround for the uv 0.11.8 hidden-`.pth` bug. See Operational notes.
- **`uv run --no-sync` pattern**: required everywhere automation drives uv; same root cause.
- **Pytest pythonpath**: workspace `pyproject.toml` sets it explicitly; same root cause.
- **Build backend**: `uv_build` (original spec did not pin one).
- **Tree additions vs original spec**: `bridge/src/bridge/middleware.py`, `bridge/src/bridge/logging_setup.py`, `bridge/src/bridge/__main__.py`, `bridge/src/bridge/routes/auth.py`, `scripts/run-bridge.sh`, `scripts/check-boundaries.sh`. The `ops/scripts/` subfolder is collapsed into top-level `scripts/`.
- **Tooling additions**: ruff line-length 100 with `ANN`/`BLE`/`T20`; pytest `filterwarnings = ["error"]`.
