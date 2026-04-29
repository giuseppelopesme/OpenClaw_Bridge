# Session 1 — repo scaffold + bridge skeleton

Date: 2026-04-29

## What landed

Step 1 of the locked build order (`CLAUDE.md` → "Build order"): repo scaffold,
uv workspace, bridge skeleton with `/v1/health`, auth middleware, error
envelope, request-id propagation, structured JSON logging, tests, CI, pre-commit.

### Repo

- Root: `README.md`, `CLAUDE.md`, `.gitignore`, `.env.example`, `pyproject.toml` (workspace).
- `docs/`: identical mirrors of the four vault spec files (`api-contract.md`,
  `event-bus.md`, `repo-layout.md`, `telemetry-plan.md`). Update both in lock-step.
- `bridge/`, `relays/imessage/`, `brains/shared/`, `brains/clu/`: each a uv
  workspace member with its own `pyproject.toml`. Stubs (`relays/imessage`,
  `brains/shared`, `brains/clu`) ship empty `__init__.py` only.
- `ops/`, `tools/`, `scripts/`, `.github/workflows/`: directories created;
  populated where step 1 needs them.

### Bridge (`bridge/src/bridge/`)

- `main.py` — `create_app()` factory + module-level `app` for `uvicorn bridge.main:app`.
- `__main__.py` — `python -m bridge` entrypoint that configures JSON logging
  before booting uvicorn. Used by `scripts/run-bridge.sh`.
- `config.py` — env-driven `Settings` dataclass (BRIDGE_HOST/PORT/LOG_LEVEL/TOKEN_STORE).
- `logging_setup.py` — stdlib `logging` + custom JSON formatter writing to stderr.
- `errors.py` — `BridgeError` base + a subclass per documented code, plus
  exception handlers (`BridgeError`, `StarletteHTTPException`, `RequestValidationError`).
  `Exception` handler is *not* registered with FastAPI — see "Design notes".
- `auth.py` — `TokenStore` reads `~/.openclaw/tokens.dev.json` (path overridable via
  `BRIDGE_TOKEN_STORE`), reloads on mtime change. `require_auth` /
  `require_scope(scope)` dependencies.
- `middleware.py` — plain ASGI `RequestIDMiddleware` (stamps `X-Request-ID` and
  `X-Bridge-Version`, catches unhandled exceptions and writes a 500 envelope
  itself) + `AccessLogMiddleware` (one structured JSON log line per request).
- `routes/health.py` — `GET /v1/health` returning the documented shape with
  every dep stubbed to `"ok"`.
- `routes/auth.py` — `GET /v1/auth/whoami` (any valid token; returns `{actor, scopes[]}`).
  Acts as the anchor endpoint for auth tests until real scoped routes land.

### Tests (`bridge/tests/`)

29 tests, all green. Organised into `unit/`:

- `test_health.py` — shape, no-auth requirement, `X-Bridge-Version` header.
- `test_request_id.py` — generated, echoed, present on error responses.
- `test_auth.py` — 401 paths (missing / malformed / unknown token), 200 happy
  path, `require_scope` unit tests, `TokenStore` hot-reload on file mtime change.
- `test_errors.py` — every documented `BridgeError` subclass renders the right
  envelope shape; integration coverage for 404, 405, 409, 500.

### Tooling

- `pyproject.toml` (root): `[tool.ruff]` (line-length 100, broad rule selection
  including `ANN`, `BLE`, `T20`), `[tool.mypy]` (strict; `bridge/src` and
  `brains/shared/src`), `[tool.pytest.ini_options]` (asyncio auto, `filterwarnings = ["error"]`).
- `.pre-commit-config.yaml` — ruff check, ruff format check, mypy, boundary
  check on every commit; pytest on push. All hooks invoke `uv run --no-sync`
  to keep the venv stable between runs (see "uv editable-install workaround").
- `.github/workflows/ci.yml` — `uv sync --group dev` once, then
  `uv run --no-sync` for ruff, ruff-format, mypy, the boundary script, and pytest.
- `scripts/check-boundaries.sh` — grep-based enforcement of the package
  boundaries spelled out in `docs/repo-layout.md`. Replaces the hand-wavey
  ruff banned-api rule the spec mentions; ruff cannot express directory-scoped
  allow-lists.
- `scripts/run-bridge.sh` — production launcher. See "Known issues" for why
  it sets `PYTHONPATH` explicitly.

## Verification

```bash
uv sync --group dev                         # 31 packages, all from the locked stack
uv run --no-sync pytest -q                  # 29 passed
uv run --no-sync ruff check .               # all checks passed
uv run --no-sync ruff format --check .      # 19 files already formatted
uv run --no-sync mypy                       # success: no issues found in 12 source files
bash scripts/check-boundaries.sh            # OK
./scripts/run-bridge.sh                     # serves /v1/health on 127.0.0.1:8788 with JSON logs
```

The DoD command `uv run uvicorn bridge.main:app --port 8788` works after the
initial `uv sync --group dev`, but only intermittently: uv 0.11.x re-runs
the editable install on every `uv run` and the resulting `.pth` state is
non-deterministic on macOS (see below). The canonical, reliable production
command is `./scripts/run-bridge.sh` — it sets `PYTHONPATH` explicitly,
passes `--no-sync` so uv does not re-install, and turns on JSON logging.

## Design notes & deviations from the spec

### `Exception` handler lives in middleware, not in `errors.install`

Starlette routes a `Exception` / `500` handler registered via
`add_exception_handler` to its own `ServerErrorMiddleware`, which is the
*outermost* middleware in the stack — outside any user middleware we add. That
middleware writes its response through the original `send`, bypassing the
header-stamping wrapper installed by `RequestIDMiddleware`. The result: 500
responses from unhandled exceptions would lack `X-Request-ID`, breaking the
spec's invariant that the header is on every response.

Fix: catch unhandled exceptions inside `RequestIDMiddleware` itself and emit
the spec envelope from there. The catch is at the *outermost* user-facing
middleware so headers always attach.

### Plain ASGI middlewares, not `BaseHTTPMiddleware`

Same root cause. `BaseHTTPMiddleware`'s anyio-based exception handling
short-circuits its post-response code on exceptions, which would also break
header stamping. Plain ASGI middlewares wrapping `send` work cleanly.

### Integer HTTP status literals

`fastapi.status.HTTP_422_UNPROCESSABLE_ENTITY` triggers a deprecation warning
under starlette 1.0 (RFC 9110 renamed it to "Unprocessable Content"). With
`filterwarnings = ["error"]` in pytest config that breaks the test run. We
use plain integer literals (matching `docs/api-contract.md` exactly) to avoid
coupling to starlette/FastAPI status-name churn.

### uv editable-install workaround

uv 0.11.8 generates editable workspace `.pth` files with the macOS
`UF_HIDDEN` flag set. Python 3.13's `site.py` skips hidden `.pth` files
(check is `st.st_flags & stat.UF_HIDDEN` in `site.addpackage`). Net effect:
workspace packages are not on `sys.path` in the venv, so `import bridge`
falls back to a namespace package rooted at the repo (which is wrong) or
fails outright.

`chflags nohidden` clears the flag, but uv re-applies it on every `uv run`
that re-syncs. Worse, repeated `uv run` cycles can leave the venv partially
broken (pytest / mypy entry points failing to import their packages),
because uv re-links workspace members non-atomically. We side-step the
whole thing with two complementary moves:

1. **Skip re-sync on every invocation.** `uv run --no-sync` is the standard
   form everywhere we drive uv from automation: pre-commit hooks, CI steps,
   and `scripts/run-bridge.sh`. The pattern is `uv sync --group dev` once
   (CI step, fresh dev checkout) and `uv run --no-sync ...` for everything
   that follows.
2. **Make `sys.path` explicit where uv's `.pth` is unreliable.**
   - Tests: `[tool.pytest.ini_options].pythonpath` puts each workspace
     `src/` directory on the path regardless of `.pth` state.
   - Production: `scripts/run-bridge.sh` exports `PYTHONPATH` before
     exec'ing `python -m bridge`.

The Session 1 prompt's DoD command `uv run uvicorn bridge.main:app --port 8788`
works after a fresh `uv sync` but cannot be relied on across repeated
invocations. The reliable equivalent is `./scripts/run-bridge.sh`. When uv
ships a fix, the cleanup is mechanical: drop `--no-sync` from CI, pre-commit,
and the launcher; remove `[tool.pytest.ini_options].pythonpath` and the
`PYTHONPATH` export. The workaround comments in those files are explicitly
flagged so they are easy to find and remove.

### Build backend: `uv_build`, not `hatchling`

The spec did not pin a build backend. We started with `hatchling` and the
`.pth` problem reproduced identically; switching to `uv_build` did not fix it
either (same hidden-flag behaviour) but is the more natural choice for a
uv-managed workspace and removes an extra dep from the lockfile.

### Boundary enforcement via shell script, not ruff

`docs/repo-layout.md` says boundaries are enforced via "ruff + a custom rule".
Ruff's `flake8-tidy-imports` cannot express directory-scoped allow-lists,
which is what the rule actually requires. `scripts/check-boundaries.sh` is a
small grep-based check that runs in CI and pre-commit; trivially extensible.

### Git identity

Repo-local `user.name = "Giuseppe Lopes"`, `user.email = giuseppe@glysk.dev` set
because no global identity was configured. Feel free to override.

## Known issues / TODO for next session

1. **uv editable-install workaround is ugly.** Track upstream uv issue; when
   fixed, drop `--no-sync` from CI / pre-commit / `scripts/run-bridge.sh`,
   remove `[tool.pytest.ini_options].pythonpath` and the `PYTHONPATH` export
   in the launcher, and tidy the linked README and `CLAUDE.md` notes.
2. **`docs/openapi-v1.yaml` is gitignored but not yet generated.** Step 8
   (Brain SDK) needs it. Add a `tools/dump-openapi.py` then.
3. **No real Keychain integration.** Step 1 deliberately uses a JSON file at
   `~/.openclaw/tokens.dev.json`. Replace before running anything that handles
   real secrets — i.e. before the LLM router (step 3) lands.
4. **Idempotency middleware not started.** Spec accepts the header; storage
   and replay come with the first POST endpoint (vault write, step 2).
5. **Rate limiting not started.** Same — wire in step 2 with the first scoped
   POST endpoint.

## What Session 2 should pick up

Step 2 of the build order: vault provider + `vault:read` / `vault:write`
endpoints. That's the natural place to introduce the idempotency middleware
and the rate-limiter, since both gate POST traffic. The vault root path
(`OBSIDIAN_VAULT` in `.env.example`) is already plumbed through `Settings`-
adjacent territory; extend rather than replace.
