---
created: 2026-04-29
source: claude-conversation
topic: openclaw monorepo layout
status: active
---

# Repo Layout

Single Git repository: `glysk/openclaw` on private GitHub. Mono-repo with three first-class concerns — bridge, relays, brains — and a shared SDK package consumed by the brains.

## Tree

```
openclaw/
├── README.md
├── pyproject.toml              # workspace root, declares packages
├── uv.lock                     # uv for env management
├── .env.example
├── .gitignore
├── .github/workflows/
│   ├── ci.yml                  # ruff + mypy + pytest matrix per package
│   └── release.yml
├── docs/
│   ├── api-contract.md         # mirrors Obsidian; this is source of truth
│   ├── event-bus.md
│   ├── openapi-v1.yaml         # generated from FastAPI app
│   └── runbooks/
│       ├── bridge-restart.md
│       ├── relay-recovery.md
│       └── token-rotation.md
├── bridge/
│   ├── pyproject.toml
│   ├── src/bridge/
│   │   ├── __init__.py
│   │   ├── main.py             # FastAPI app entry
│   │   ├── config.py           # env + keychain loading
│   │   ├── auth.py             # token validation, scope check
│   │   ├── errors.py           # error envelope, exception handlers
│   │   ├── idempotency.py      # idempotency-key middleware
│   │   ├── ratelimit.py        # token bucket
│   │   ├── telemetry.py        # SQLite writer + access log
│   │   ├── routes/
│   │   │   ├── health.py
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
│   │   ├── com.glysk.openclaw.bridge.plist
│   │   ├── com.glysk.openclaw.redis.plist
│   │   ├── com.glysk.openclaw.relay.clu.plist
│   │   ├── com.glysk.openclaw.relay.tron.plist
│   │   ├── com.glysk.openclaw.relay.flynn.plist
│   │   └── com.glysk.openclaw.brain.clu.plist
│   ├── redis/redis.conf
│   ├── install.sh              # bootstraps from a fresh macOS
│   └── scripts/
│       ├── mint-token.py
│       ├── rotate-token.py
│       └── health-check.sh
└── tools/
    ├── claw                    # admin CLI (mint tokens, tail events, replay)
    └── claw-tui                # optional curses dashboard
```

## Package boundaries

The boundaries below are not aspirational — they're enforced by import linting (`ruff` + a custom rule that fails CI on cross-package imports outside the allowed set).

- `bridge` knows about Apple, email, vault, Redis, and LLM providers. Speaks no agent logic. Never imports from `relays/` or `brains/`.
- `relays/imessage` knows only `chat.db` and AppleScript. Talks to the bridge over HTTP using a thin client. Never imports from `bridge/` or `brains/`.
- `brains/shared` is the typed SDK every brain uses to call the bridge. Generated from the OpenAPI spec. Never imports from `bridge/` (it consumes the spec, not the code).
- `brains/{name}` knows only its own logic and `brains_shared`. Never imports from `bridge/` or `relays/`.

The point is brutal: if Tron's brain breaks, it cannot bring down the bridge or CLU's relay. If a relay crashes, the bridge keeps serving. If the bridge restarts, relays and brains reconnect cleanly.

## Tooling

- Python 3.13, `uv` for env and lockfile management
- `ruff` for lint + format (replaces black + isort + flake8)
- `mypy --strict` on `bridge/` and `brains/shared/`. Brains and relays start at `--strict` from day one — easier than retrofitting.
- `pytest` with `pytest-asyncio` for the bridge
- Pre-commit hooks: ruff, mypy, pytest on changed packages
- CI on GitHub Actions, matrix per package, integration tests against a Redis service container

## Bootstrap

`ops/install.sh` runs from a fresh macOS and is itself versioned. Steps:

1. Create `clu`, `tron`, `flynn` users (idempotent)
2. Install Homebrew, Python 3.13, Redis, `uv`
3. Clone the repo to `/Users/giuseppelopes/openclaw`
4. Generate Redis password and bridge token salt, store in Keychain
5. Mint initial tokens for each component
6. Install launchd plists (bridge → redis → relays → brains, in dependency order)
7. Run health check

The whole bootstrap should be reproducible end-to-end in under 10 minutes on the M4.


---

## Amendments — 2026-04-29 (Session 1)

These supersede the corresponding parts of the spec above. Reasons documented in `SESSION-NOTES.md` from Session 1.

### Repo location

The repo lives at `~/Developer/openclaw` on the Mac Mini, not `~/openclaw`. Update launchd plists, install scripts, and any documentation accordingly.

### Boundary enforcement is a shell script, not ruff

`scripts/check-boundaries.sh` is the canonical boundary enforcer. It runs in pre-commit and CI. Ruff's `flake8-tidy-imports` cannot express directory-scoped allow-lists, which is what the boundary rule actually requires. The shell script is grep-based, trivially extensible, and good enough.

### Canonical launcher: `./scripts/run-bridge.sh`

The DoD command `uv run uvicorn bridge.main:app --port 8788` works after a fresh `uv sync` but **cannot be relied on across repeated invocations**. uv 0.11.8 generates editable workspace `.pth` files with the macOS `UF_HIDDEN` flag set, and Python 3.13's `site.py` skips hidden `.pth` files. The result: workspace packages drop off `sys.path` non-deterministically.

Two complementary workarounds, both currently in place:

1. **`uv run --no-sync` everywhere uv is driven from automation.** Pre-commit hooks, CI steps, and `scripts/run-bridge.sh` all use `--no-sync`. The pattern is `uv sync --group dev` once (CI step or fresh dev checkout) and `uv run --no-sync ...` for everything that follows.
2. **Explicit `sys.path` where uv's `.pth` is unreliable:**
   - Tests: `[tool.pytest.ini_options].pythonpath` in root `pyproject.toml` puts each workspace `src/` directory on the path regardless of `.pth` state.
   - Production: `scripts/run-bridge.sh` exports `PYTHONPATH` before exec'ing `python -m bridge`.

When uv ships a fix, the cleanup is mechanical: drop `--no-sync` from CI / pre-commit / launcher, remove `pythonpath` from pytest config, remove the `PYTHONPATH` export from the launcher. All workaround sites carry an explicit comment so they are easy to find.

### Build backend: `uv_build`

The original spec did not pin a build backend. The repo uses `uv_build` rather than `hatchling` — natural choice for a uv-managed workspace, one fewer dep in the lockfile.

### Tooling additions over original spec

- `[tool.ruff]` configured with line-length 100 and broad rule selection including `ANN`, `BLE`, `T20`.
- Pre-commit hooks: ruff check, ruff format check, mypy, boundary script on commit; pytest on push.
- All hooks invoke `uv run --no-sync` per the workaround above.


### Repo location — correction

The previous amendment said `~/Developer/openclaw`. The correct path is `~/Developer/OpenClaw/OpenClaw_Bridge` (parent `OpenClaw/` is reserved for the umbrella; bridge code lives in the `OpenClaw_Bridge/` subfolder). Update launchd plists, install scripts, and `ops/install.sh` step 3 accordingly.


---

## Path correction — 2026-04-29 (post-iCloud)

The earlier amendment said `~/Developer/openclaw`. Canonical path is `~/Developer/OpenClaw_Bridge`. Repo briefly lived inside iCloud Drive and was moved out after sync conflicts created duplicate `uv.lock` copies. iCloud is unsuitable for live codebases (venv eviction, conflict copies on writes, slow Git operations) — for cross-machine sync, push to GitHub.

Update launchd plists, install scripts, and any tooling that hardcodes a repo path accordingly.
