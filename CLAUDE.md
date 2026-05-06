# OpenClaw

Personal-AI bridge for macOS. One bridge, one configurable brain, one
iMessage relay. Single Mac Mini host.

## Status

The full installation experience is production-ready: a single signed
+ notarized `MacOSBridgeForOpenClaw.pkg` drops `OpenClawBridge.app`
and `OpenClawRelay.app` into `/Applications/`, picks the iMessage
service user(s) via an osascript dialog at install time, and registers
both LaunchAgents via `SMAppService.agent(plistName:)` in the right
per-user Aqua sessions (no plists copied into user homes). Login
Items / App Background Activity displays them under their bundle
display names — "MacOS Bridge for OpenClaw" and "OpenClaw Relay" —
not the Developer-ID team name. Redis ships bundled inside the
bridge .app's `Contents/MacOS/` (started by the supervisor as the
first ordered child); no external Redis service required. The
bridge supervisor sequences redis → bridge → brain, each gated on
the previous's TCP readiness. End-to-end iMessage round-trip
(phone → chat.db → relay → bridge → brain → draft → operator
approval → osascript send) is unblocked.

The codebase is **agent-agnostic and account-agnostic** by design:
operators choose any well-formed identifier for the brain (default
`"agent"`) and any macOS user account for the relay. No brand or
persona names are baked into the source tree.

## Architecture in brief

- `bridge/` — FastAPI on `127.0.0.1:8788`, runs as the operator. The
  only component that talks to Apple, IMAP/SMTP, Redis, LLM providers,
  vault.
- `relays/imessage/` — thin process (~200 LOC) running as a *separate*
  macOS user account. Polls `chat.db`, sends via osascript, talks to
  the bridge over loopback. Nothing else. Shipped as
  `OpenClawRelay.app` — Developer-ID-signed, notarized.
- `brains/agent/` — agent process running as the operator. Talks only
  to the bridge via the typed `brains/shared` SDK. Subscribes to
  `imessage.received.{agent}`, runs LLM triage + draft, publishes
  `agent.{agent}.draft.pending` and creates the draft in the bridge's
  drafts table.
- `brains/shared/` — the typed SDK every brain uses. Generated
  `_generated/` tree from the OpenAPI spec; hand-written wrappers
  on top.
- Event bus: Redis pub/sub on `127.0.0.1:6379`, mediated exclusively
  by the bridge.

The brain identity (`AGENT_NAME` in env, e.g. `agent`) and the
service user account name (e.g. whatever the operator picked at
install time) are **independent concepts**. Topic names, Keychain
actor keys, and state-DB filenames are parametric on either or both:

| Identifier | Source                        | Used in                                                                |
| ---------- | ----------------------------- | ---------------------------------------------------------------------- |
| `<agent>`  | `AGENT_NAME` env              | topic `imessage.received.{agent}`, Keychain `brain.{agent}`, state DB  |
| `<account>`| `getpass.getuser()` at runtime| Keychain `relay.{account}`, log filename `relay.{account}.log`         |

## Source of truth

The spec lives in the Obsidian vault at `01 - Projects/OpenClaw/Bridge/`:

- `API Contract v1.md`
- `Event Bus.md`
- `Repo Layout.md`
- `Telemetry Plan.md`

Mirror these into `docs/` in the repo as identical markdown. Vault
copies are the human source; `docs/` makes the repo self-contained.
Update both together — never one without the other.

The OpenAPI spec generated from the bridge code lives at
`docs/openapi-v1.yaml`. The pre-commit hook fails any commit where the
YAML drifts from `bridge.main:app.openapi()`. To regenerate:
`tools/regen-sdk.sh`.

## Tech stack (locked)

- Python 3.13
- `uv` for env and lockfile management; workspace at repo root; build
  backend `uv_build`
- FastAPI for the bridge HTTP layer
- `httpx` for OpenRouter (and future) HTTP clients; the iMessage
  relay uses sync `httpx.Client`; brains use the async
  `httpx.AsyncClient` via the generated SDK
- `redis-py` async + `websockets` for the event bus; brains consume
  the WebSocket subscriber via `brains_shared.eventbus`
- stdlib `sqlite3` for telemetry + idempotency cache + brain state
- stdlib `imaplib` + `smtplib`, wrapped in `asyncio.to_thread`, for email
- `keyring` for macOS Keychain access. The relay reads its keychain
  slot via `/usr/bin/security` subprocess (no Python dep, matches the
  project's "shell out to Apple binaries" pattern).
- `python-frontmatter` for vault writes
- `attrs` for the generated SDK's model classes; `pyyaml` for
  `tools/dump-openapi.py`
- `openapi-python-client` (dev-only) — generates
  `brains/shared/src/brains_shared/_generated/`
- `pyinstaller` (dev-only) — freezes both .app bundles
- `pytest` + `pytest-asyncio`
- `ruff` for lint and format (`brains/shared/_generated/` is excluded
  — auto-managed)
- `mypy --strict` on `bridge/` and `brains/shared/` (covers the
  `_generated/` tree too)

Adding a dependency not in this list requires a conversation first.
PyObjC is explicitly NOT in the stack — Apple integration uses
osascript subprocesses, Messages.app dispatch likewise, and
SMAppService registration goes through a Swift `openclaw-register`
helper bundled inside each .app.

## Naming convention

Reverse-DNS namespace for everything that needs one (Keychain
service IDs, launchd plist labels, bundle identifiers, etc.) is
`me.lopes.openclaw.<component>`.

## Conventions

- Cross-package imports are forbidden except `brains/*` →
  `brains/shared`. Enforced by `scripts/check-boundaries.sh`. The
  relay (`relays/imessage/*`) is *its own* boundary too — it never
  imports from `bridge/` or `brains/`, and its standalone
  JSON-stderr logger mirrors but does not depend on the bridge's
  `logging_setup`.
- Brains never import from `brains_shared._generated` directly — the
  public surface is `brains_shared.{client,eventbus,events,obsidian,llm,agent,imessage}`.
  The generated tree is auto-managed; touching it by hand will be
  overwritten by `tools/regen-sdk.sh`.
- Every endpoint ships with at least one happy-path test and one
  error-path test before it's considered done.
- Every error response uses the envelope from API Contract v1. No
  exceptions.
- Structured JSON logs to stderr. No `print()`.
- No bare `except:`. Catch the narrowest exception that fits.
- Type-annotate everything, including private helpers.
- New endpoints go in `bridge/src/bridge/routes/<domain>.py` and
  register in `main.py`. No god-route file.
- Test basenames must be globally unique across all `tests/` trees in
  the workspace (`test_brain_*`, `test_apple_*`, `test_brains_*`,
  etc.) — pytest can't disambiguate two same-named files in different
  trees without `__init__.py`-as-package, and we don't use those.
- Brain handlers are responsible for their own dedup via
  `state.is_processed(event_id)` at the top, and for their own
  poison-pill defence (mark processed even on handler error, so a
  malformed envelope can't loop the brain).
- Commit small, commit often. Each commit is a green test run.
- Secrets live in macOS Keychain. Never in `.env`, never in JSON on
  disk, never in source. The pkg installer's postinstall mints the
  `brain.{agent}` and `relay.{account}` Keychain entries; plists
  never carry plaintext placeholders. The `RELAY_TOKEN` /
  `BRAIN_TOKEN` env vars still win when set (useful for tests/dev)
  but are not needed at production launch.

## Operational rules (uv 0.11.8 workaround in force)

- The canonical production launcher is `./scripts/run-supervisor.sh`.
  It owns the bridge + brain pair under a single parent process via
  `bridge.supervisor`. Health-gates the brain on the bridge's
  `/v1/health`, restarts crashed children with exponential backoff,
  and treats 3 crashes in 30 s as a poison-pill (exits non-zero so
  launchd can decide).
- For dev/tests, `./scripts/run-bridge.sh` runs the bridge alone (no
  brain) and `./scripts/run-brain.sh` runs the brain alone against
  an already-running bridge.
- The canonical relay distribution is `OpenClawRelay.app`, built via
  `bundle/relay/build.sh` and installed via the pkg's postinstall (or
  for dev bringup, `scripts/setup-relay-account.sh`). The .app
  embeds its own LaunchAgent template at
  `Contents/Library/LaunchAgents/`; SMAppService consumes it directly
  from inside the .app — no copies in `~/Library/LaunchAgents/`.
- All automation uses `uv run --no-sync …` after a single
  `uv sync --group dev`.
- See `docs/repo-layout.md` § Operational notes for the rationale and
  the cleanup path when uv ships a fix.

## Stop and ask before

- Adding a dependency not in the stack above
- Changing the API contract (vault docs are authoritative; we update
  them together)
- Touching anything under `06 - Archive/` in the vault
- Modifying or installing launchd plists / `.app` bundle entitlements
  for the first time
- Storing real secrets anywhere outside macOS Keychain
- Hand-editing any file under
  `brains/shared/src/brains_shared/_generated/` (regenerate via
  `tools/regen-sdk.sh` instead)
- Hand-editing build artefacts under `bundle/relay/dist/` or
  `bundle/relay/build/` (rebuild via `bundle/relay/build.sh` instead)
- Renaming or restructuring the brain package (`brains/agent/`) — the
  package layout is a stable contract for downstream forks and
  customisations

## Working principles

- Direct and concise. No preamble.
- When unclear, ask once, then proceed.
- Decisions and frameworks beat raw detail.
- If a yes/no question is asked, lead with the answer.
