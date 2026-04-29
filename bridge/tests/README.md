# Bridge tests

The default suite is hermetic — it never touches the real macOS Keychain or
the real Obsidian vault. `tests/conftest.py` swaps `bridge.keychain`'s
backend for an in-memory fake before any test runs and points each test at a
tempfile vault.

## Running

```
uv run --no-sync pytest                  # default: full hermetic suite
uv run --no-sync pytest -m macos_keychain  # opt-in: real Keychain integration
```

The `macos_keychain`-marked tests are skipped by default (see
`pytest_collection_modifyitems` in `conftest.py`). They write a single
`openclaw.test._do_not_keep_` item, read it back, and delete it. macOS may
prompt for Keychain access on first run.

## Test boundaries

- `unit/` — pure unit + FastAPI TestClient, no network, no real Keychain.
- The `tokens` fixture seeds the fake Keychain; `vault_root` provisions a
  tempfile vault with a single canned page (`Inbox/hello.md`).
- The `client` fixture builds a fresh app per test; lifespan runs migrations
  on a tempfile SQLite file.
