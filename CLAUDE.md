# OpenClaw

Personal AI agent ecosystem. One bridge, three brains (CLU, TRON, FLYNN), three iMessage relays. Single Mac Mini M4 host.

## Status

Build in progress. Sessions 1–9 shipped, plus the P1a refactor (bridge-side drafts + approval flow), the production bringup of CLU (2026-05-03 → 04), and the Session 10a relay re-platform (relay shipped as a Developer-ID-signed `.app` bundle). The end-to-end iMessage round-trip — phone → chat.db → relay → bridge → brain → draft → operator approval → osascript send — is now unblocked: the read pipeline was verified live on 2026-05-04, and the send pipeline's Automation: Messages.app prompt now anchors to the signed `OpenClawRelay.app` identity. Session 10 (TRON + FLYNN) is deferred behind two prerequisites: (a) E2E send round-trip verified with the .app bundle, (b) the bridge-side `OpenClawBridge.app` re-platform (Session 10b) — re-platforming after Session 10 means three brain packages get re-platformed instead of one.

## Architecture in brief

- `bridge/` — FastAPI on `127.0.0.1:8788`, runs as `giuseppelopes`. The only component that talks to Apple, IMAP/SMTP, Redis, LLM providers, vault.
- `relays/imessage/` — thin processes (~200 LOC each) running as `clu`, `tron`, `flynn` macOS users. Poll `chat.db`, send via osascript, talk to the bridge over loopback. Nothing else. Shipped as `OpenClawRelay.app` — Developer-ID-signed, notarized — since Session 10a.
- `brains/{clu,tron,flynn}/` — agent processes running as `giuseppelopes`. Talk only to the bridge via the typed `brains/shared` SDK. Never to each other directly. Each brain subscribes to `imessage.received.{name}`, runs LLM triage + draft, publishes `agent.{name}.draft.pending`.
- Event bus: Redis pub/sub on `127.0.0.1:6379`, mediated exclusively by the bridge.

## Source of truth

The spec lives in the Obsidian vault at `01 - Projects/OpenClaw/Bridge/`:

- `API Contract v1.md`
- `Event Bus.md`
- `Repo Layout.md`
- `Telemetry Plan.md`

Mirror these into `docs/` in the repo as identical markdown. Vault copies are the human source; `docs/` makes the repo self-contained. Update both together — never one without the other.

The OpenAPI spec generated from the bridge code lives at `docs/openapi-v1.yaml` (Session 8). The pre-commit hook fails any commit where the YAML drifts from `bridge.main:app.openapi()`. To regenerate: `tools/regen-sdk.sh`.

## Tech stack (locked)

- Python 3.13
- `uv` for env and lockfile management; workspace at repo root; build backend `uv_build`
- FastAPI for the bridge HTTP layer
- `httpx` for OpenRouter (and future) HTTP clients (added in Session 3); the iMessage relay uses sync `httpx.Client` (Session 7); brains use the async `httpx.AsyncClient` via the generated SDK (Session 8)
- `redis-py` async + `websockets` for the event bus (added in Session 4); brains consume the WebSocket subscriber via `brains_shared.eventbus` (Session 8)
- stdlib `sqlite3` for telemetry + idempotency cache (Session 2 chose sync over `aiosqlite`; SQLite ops are fast enough that the threading bridge isn't worth it). The relay's chat.db cursor uses the same stdlib API in read-only mode (Session 7). Brains use the same pattern for their state DB (Session 9 — dedup + drafts table)
- stdlib `imaplib` + `smtplib`, wrapped in `asyncio.to_thread`, for email (Session 6 — same pattern as SQLite; declined `aiosmtplib`/`aioimaplib`)
- `keyring` for macOS Keychain access (Session 2). The relay reads its keychain slot via `/usr/bin/security` subprocess (Session 10a) — no Python dep, matches the project's "shell out to Apple binaries" pattern.
- `python-frontmatter` for vault writes (Session 2)
- `attrs` for the generated SDK's model classes; `pyyaml` for `tools/dump-openapi.py` (Session 8)
- `openapi-python-client` (dev-only) — generates `brains/shared/src/brains_shared/_generated/` from the OpenAPI YAML (Session 8)
- `pyinstaller` (dev-only, Session 10a) — freezes `relays/imessage` into `OpenClawRelay.app/Contents/MacOS/`. Build-time only; never imported at runtime.
- `pytest` + `pytest-asyncio`
- `ruff` for lint and format (`brains/shared/_generated/` is excluded — auto-managed)
- `mypy --strict` on `bridge/` and `brains/shared/` (covers the `_generated/` tree too) from day one. Brain packages (`brains/clu/`, future `brains/tron/`, `brains/flynn/`) are type-annotated but not in the strict-checked set — boundaries between them and `brains_shared` are the contract that matters.

Adding a dependency not in this list requires a conversation first. PyObjC is explicitly NOT in the stack — Apple integration uses osascript subprocesses (Session 5), Messages.app dispatch likewise (Session 7), and SMAppService registration is replaced with a plain LaunchAgent that exec's the .app's signed binary (Session 10a).

## Naming convention

Reverse-DNS namespace for everything that needs one (Keychain service IDs, launchd plist labels, bundle identifiers, etc.) is `com.giuseppelopesme.openclaw.<component>`. Matches the GitHub username for visual consistency. OpenClaw is personal infrastructure with no organisational owner — never use any other namespace.

## Conventions

- Cross-package imports are forbidden except `brains/*` → `brains/shared`. Enforced by `scripts/check-boundaries.sh`. The relay (`relays/imessage/*`) is *its own* boundary too — it never imports from `bridge/` or `brains/`, and its standalone JSON-stderr logger mirrors but does not depend on the bridge's `logging_setup`.
- Brains never import from `brains_shared._generated` directly — the public surface is `brains_shared.{client,eventbus,events,obsidian,llm}`. The generated tree is auto-managed; touching it by hand will be overwritten by `tools/regen-sdk.sh`.
- Every endpoint ships with at least one happy-path test and one error-path test before it's considered done.
- Every error response uses the envelope from API Contract v1. No exceptions.
- Structured JSON logs to stderr. No `print()`.
- No bare `except:`. Catch the narrowest exception that fits.
- Type-annotate everything, including private helpers.
- New endpoints go in `bridge/src/bridge/routes/<domain>.py` and register in `main.py`. No god-route file.
- Test basenames must be globally unique across all `tests/` trees in the workspace (`test_brains_*`, `test_apple_*`, `test_clu_*`, etc.) — pytest can't disambiguate two same-named files in different trees without `__init__.py`-as-package, and we don't use those.
- Brain handlers are responsible for their own dedup via `state.is_processed(event_id)` at the top, and for their own poison-pill defence (mark processed even on handler error, so a malformed envelope can't loop the brain). Documented in Session 9's handler.
- Commit small, commit often. Each commit is a green test run.
- Secrets live in macOS Keychain. Never in `.env`, never in JSON on disk, never in source. As of 2026-05-03 there are NO exceptions — `scripts/run-clu.sh` loads its bearer token from Keychain at launch (`brain.clu` actor), and `OpenClawRelay.app` reads `relay.{agent}` from the running user's login keychain via `relay.keychain_reader` on startup. Plists never carry plaintext placeholders. The `RELAY_TOKEN` / `BRAIN_TOKEN` env vars still win when set (useful for tests/dev) but are not needed at production launch.

## Operational rules (uv 0.11.8 workaround in force)

- The canonical bridge launcher is `./scripts/run-bridge.sh`. Do not invoke `uv run uvicorn …` for anything beyond a one-shot manual smoke test.
- The canonical CLU launcher is `./scripts/run-clu.sh`. (Future: `run-tron.sh`, `run-flynn.sh`.)
- The canonical relay distribution is `OpenClawRelay.app`, built via `bundle/relay/build.sh` and installed via `scripts/setup-clu-account.sh`. There is no `scripts/run-relay.sh` — that was retired in Session 10a along with `ops/launchd/com.giuseppelopesme.openclaw.relay.clu.plist`. The .app embeds its own LaunchAgent template at `Contents/Library/LaunchAgents/`; the install step copies it into `~/Library/LaunchAgents/`.
- All automation uses `uv run --no-sync …` after a single `uv sync --group dev`.
- See `docs/repo-layout.md` § Operational notes for the rationale and the cleanup path when uv ships a fix.

## Build order (locked)

Each step is independently testable and shippable. Don't reorder without a conversation.

1. Repo scaffold + bridge skeleton (FastAPI app, auth middleware, error envelope, `/v1/health`) ✓ Session 1
2. Keychain + vault provider + idempotency + rate limiter ✓ Session 2
3. LLM router + OpenRouter provider + `/v1/llm/complete` + telemetry + real `/v1/health` ✓ Session 3
4. Redis event bus + `events:publish` / `events:subscribe` + Redis-backed rate limiter + real `vault.changed` ✓ Session 4
5. Apple provider (calendar, reminders, contacts) + endpoints + real `apple_bridge` probe ✓ Session 5
6. IMAP/SMTP provider + email endpoints + real `imap_*` probes ✓ Session 6
7. iMessage relay (CLU only) + `imessage:send` / `imessage:relay` + outbound queue ✓ Session 7
8. Brain SDK (`brains/shared`) generated from the OpenAPI spec ✓ Session 8
9. CLU brain — first event subscriber, full end-to-end loop ✓ Session 9
10a. Relay as Developer-ID-signed `.app` bundle ✓ Session 10a
10b. Bridge + brain.clu as Developer-ID-signed `.app` (deferred — supervisor process refactor first)
10c. TRON + FLYNN brains (deferred behind 10b — re-platforming first means we don't rewrite three brain packages instead of one)

After 10c the locked build order is complete. Subsequent sessions wire the human-approval flow (`agent.{name}.draft.approved` consumer + `/v1/agent/drafts/*` endpoints), per-brain personas, and TRON/FLYNN domain-specific logic.

## Stop and ask before

- Adding a dependency not in the stack above
- Changing the API contract (vault docs are authoritative; we update them together)
- Touching anything under `06 - Archive/` in the vault
- Modifying or installing launchd plists / `.app` bundle entitlements for the first time
- Storing real secrets anywhere outside macOS Keychain
- Hand-editing any file under `brains/shared/src/brains_shared/_generated/` (regenerate via `tools/regen-sdk.sh` instead)
- Hand-editing build artefacts under `bundle/relay/dist/` or `bundle/relay/build/` (rebuild via `bundle/relay/build.sh` instead)
- Refactoring across the brain packages (CLU, TRON, FLYNN) — discuss the abstraction before extracting

## Working principles

- Direct and concise. No preamble.
- When unclear, ask once, then proceed.
- Decisions and frameworks beat raw detail.
- If a yes/no question is asked, lead with the answer.
