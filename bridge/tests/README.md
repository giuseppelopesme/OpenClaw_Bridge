# Bridge tests

The default suite is hermetic — it never touches the real macOS Keychain,
the real Obsidian vault, or osascript. `tests/conftest.py` swaps
`bridge.keychain`'s backend for an in-memory fake, points each test at a
tempfile vault, and stubs the apple_bridge probe before any test runs.

## Running

```
uv run --no-sync pytest                       # default: hermetic suite
uv run --no-sync pytest -m macos_keychain     # opt-in: real Keychain
uv run --no-sync pytest -m macos_apple        # opt-in: real osascript
```

The opt-in markers are skipped by default (see
`pytest_collection_modifyitems` in `conftest.py`):

- `macos_keychain` — writes a single `openclaw.test._do_not_keep_` item to
  the real Keychain, reads it back, deletes it. macOS may prompt for
  Keychain access on first run.
- `macos_apple` — runs an inert `osascript` call against System Events.
  macOS may prompt for Automation permissions on first run; grant once
  per resource (Calendar, Reminders, Contacts) via System Settings →
  Privacy & Security → Automation.

## Test boundaries

- `unit/` — pure unit + FastAPI TestClient, no network, no real Keychain,
  no real osascript.
- The `tokens` fixture seeds the fake Keychain; `vault_root` provisions a
  tempfile vault with a single canned page (`Inbox/hello.md`).
- The `client` fixture builds a fresh app per test; lifespan runs migrations
  on a tempfile SQLite file.
- The `fake_apple_runner` autouse fixture monkeypatches the health
  probe's `run_osascript` to return `"true"`. Apple-route tests inject
  their own runner via `CalendarProvider(runner=...)` so they bypass the
  module function entirely.

## Capturing fresh fixtures

`tools/capture-osascript-fixtures.py` runs each Apple provider once
against the live host and writes the raw runner output to
`bridge/tests/fixtures/apple/{calendar,reminders,contacts}/`. Operator-run,
not CI-run.
