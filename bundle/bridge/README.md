# `bundle/bridge/` — OpenClawBridge.app build artefacts

PyInstaller spec, plist templates, entitlements, and build/test scripts
for **OpenClawBridge.app** — the Developer-ID-signed, notarized .app
bundle that owns the bridge + `brain.agent` pair under a single signed
binary. Replaces the `scripts/run-supervisor.sh` topology in production
(the script remains the canonical dev launcher).

`CFBundleDisplayName` is **"MacOS Bridge for OpenClaw"** — the string
that appears in every TCC prompt the bridge triggers on first run
(Calendar, Contacts, Reminders, Apple Events for Notes).

## Why a single binary, multi-mode

PyInstaller bakes one entry-callable per frozen executable. The
supervisor (`bridge.supervisor`) needs to spawn `bridge` and
`brain.agent` as child processes, but a frozen binary does not accept
`-m`. Two options:

1. Ship three separate frozen executables in `Contents/MacOS/`. Three
   signatures, three TCC identities, three notarization tickets.
2. Ship one frozen executable that dispatches on `argv[1]` to the right
   internal entry point.

We picked (2). `bundle/bridge/entry.py` is the dispatch — see its
header for the contract. The supervisor's `_build_default_children`
already detects `sys.frozen` and emits the right argv shape for
production; it falls back to `python -m …` in dev.

Trade-off: the entry point imports both `bridge` and `agent` packages.
Boundary check (`scripts/check-boundaries.sh`) only scans the `bridge/`,
`brains/`, `relays/` source trees, so this cross-package import lives
correctly outside that scope.

## Files

| File | Role |
| --- | --- |
| `entry.py` | PyInstaller's entry script. Multi-mode dispatch on `argv[1]`. Imports `bridge.supervisor`, `bridge.__main__`, and `agent.__main__`. |
| `pyinstaller.spec` | PyInstaller build definition. Pulls `bridge`, `brains_shared`, and `agent` into the bundle; excludes `relay` and dev-only deps. Migration `.sql` files are added as data files (PyInstaller does not pick them up automatically). |
| Bundled `redis-server` | `build.sh` copies the host's `/opt/homebrew/bin/redis-server` (resolved through the symlink to the real Mach-O) into `Contents/Resources/redis-server`. The supervisor spawns it as its first child with config matching `ops/redis/redis.conf` — loopback only, password from Keychain (`provider.redis`, auto-generated on fresh install if absent), 256 MB memory cap, no persistence. The .pkg is therefore self-contained: a fresh `MacOSBridgeForOpenClaw.pkg` install does not need any external Redis service. The binary is signed under the same Developer ID as the rest of the bundle via `codesign --deep`. |
| `Info.plist.template` | Real `Info.plist`. Injected into the .app by `build.sh` after PyInstaller's BUNDLE step. `__VERSION__` is replaced with the bridge package version. |
| `entitlements.plist` | Code-signing entitlements. Same four keys as the relay — see "Entitlements rationale" below. |
| `launchagent.plist.template` | LaunchAgent that starts the .app at user login. Bundled at `Contents/Library/LaunchAgents/me.lopes.openclaw.bridge.plist` inside the .app; the pkg installer copies it into `~/Library/LaunchAgents/` and substitutes `__APP_PATH__` + `__LOG_DIR__`. |
| `build.sh` | Build → codesign → notarize → staple. Idempotent. Reads `TEAM_ID`, `DEV_ID_IDENTITY`, `NOTARY_PROFILE` from env. `SKIP_SIGN=1` runs PyInstaller alone for layout iteration. |
| `test_bundle.sh` | Post-build smoke test. Verifies bundle structure, Info.plist values (incl. all four TCC purpose strings), multi-mode dispatch, hardened-runtime signing, entitlements, Gatekeeper acceptance, stapled ticket. `SKIP_SIGN_CHECKS=1` matches the build's `SKIP_SIGN=1`. |
| `dist/` | Build output. Not checked in. `OpenClawBridge.app` and `OpenClawBridge.zip` (notarization payload) live here. |
| `build/` | PyInstaller intermediates. Not checked in. |

## Entitlements rationale

Each entry in `entitlements.plist` is a deliberate trade-off — same
four keys the relay ships with. Future contributors should not add or
remove keys without re-doing the analysis below.

- **`com.apple.security.automation.apple-events = true`** — ESSENTIAL.
  The bridge drives Notes (and any future Apple-app integration) via
  `osascript`. Without this entitlement macOS Sequoia denies the
  AppleEvent with `errAEEventNotPermitted` regardless of TCC grants —
  same root cause that triggered Session 10a's relay re-platform.
- **`com.apple.security.app-sandbox = false`** — ESSENTIAL (in negative
  form). The bridge needs network access (loopback for the FastAPI app,
  outbound for OpenRouter/IMAP/SMTP), filesystem access for the vault
  and the SQLite DBs at `~/.openclaw/`, and AppleEvents to user-chosen
  apps. The App Store sandbox forbids all three. Direct-distribution
  via Developer ID is the only viable path; do not enable app-sandbox
  without re-doing that analysis.
- **`com.apple.security.cs.allow-jit = true`** — TRADEOFF for
  PyInstaller's frozen interpreter. Same rationale as the relay.
  Without it: bundle launches, hardened runtime kills it instantly
  with `EXC_BAD_ACCESS (SIGKILL)`, Console reports
  `killed: 9 — code signing violation`.
- **`com.apple.security.cs.disable-library-validation = true`** —
  TRADEOFF for PyInstaller's bundled C extensions. Python 3.13 ships
  C extensions (`_ssl`, `_hashlib`, `_sqlite3`, …) signed by python.org's
  certificate, not ours. Hardened runtime would refuse to load them
  under our identity without this. Bundle surface is small and known;
  the trade-off is acceptable.

## TCC purpose strings

`Info.plist` carries four `NS*UsageDescription` entries — Calendar,
Contacts, Reminders, AppleEvents. macOS surfaces each verbatim in the
TCC prompt the first time the bridge calls into the corresponding API.
The header on every prompt reads "MacOS Bridge for OpenClaw"
(`CFBundleDisplayName`) followed by the body string from Info.plist.

Mail does not need a purpose string — IMAP/SMTP go through standard
networking with credentials in Keychain; no TCC involvement.

## Build flow

```
$ export TEAM_ID=283UY8S778
$ export DEV_ID_IDENTITY="Developer ID Application: Giuseppe Lopes (283UY8S778)"
$ export NOTARY_PROFILE=MacOs-OpenClaw.Notary
$ bundle/bridge/build.sh         # ~5 minutes (PyInstaller + notarization wait)
$ bundle/bridge/test_bundle.sh   # ~5 seconds; fails fast if anything is off
```

For layout iteration without burning notarization submissions:

```
$ SKIP_SIGN=1 bundle/bridge/build.sh
$ SKIP_SIGN_CHECKS=1 bundle/bridge/test_bundle.sh
```

After both pass: `bundle/bridge/dist/OpenClawBridge.app` is ready to ship.
The pkg installer (Step 4) copies it to `/Applications/` and installs
the embedded LaunchAgent into `~/Library/LaunchAgents/`.

## Caveats / open issues

- **No CI yet.** Same as the relay — `build.sh` requires the operator's
  signing identity and notarytool credentials, neither of which are in
  CI's hands.
- **Auto-update.** Not part of this session. Sparkle integration is
  the natural fit; out of scope for now.
- **Version drift between bundle and pyproject.toml.** `build.sh` reads
  the version from `bridge/pyproject.toml` so the .app's
  `CFBundleVersion` always tracks. If we eventually independently
  version the .app (e.g. for a beta channel), this becomes a separate
  knob.
