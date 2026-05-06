# `installer/` — `MacOSBridgeForOpenClaw.pkg` build artefacts

Distribution-package wrapper around the two `.app` bundles, plus the
postinstall script that installs LaunchAgents per user. The output is
**`MacOSBridgeForOpenClaw.pkg`** — a signed + notarized installer that
the user double-clicks once to bring up the whole OpenClaw stack.

## What the pkg does on install

1. Drops `/Applications/OpenClawBridge.app` and `/Applications/OpenClawRelay.app`.
2. Postinstall (root) detects the main user via `stat -f "%Su" /dev/console`.
3. Postinstall enumerates non-system user accounts (UID ≥ 501, not `_*`,
   not the main user, home under `/Users`) and shows an `osascript`
   "Choose from list" dialog under the main user's GUI session — the
   operator picks the macOS user account that will run the iMessage
   relay (any non-system account; the installer is account-agnostic).
4. Postinstall materialises both LaunchAgents:
   - `~main_user/Library/LaunchAgents/me.lopes.openclaw.bridge.plist`
   - `~service_user/Library/LaunchAgents/me.lopes.openclaw.relay.<service_user>.plist`
   chowning each to its owning user and substituting `__APP_PATH__`
   and `__LOG_DIR__` placeholders with the install paths.
5. Writes `/Library/Application Support/OpenClaw/config.json` recording
   the chosen topology (main user, service user, bundle paths, install
   timestamp). Future tooling reads this instead of re-prompting.
6. Bootstraps the bridge LaunchAgent immediately into the main user's
   Aqua session — the bridge starts on install, no reboot. The relay
   LaunchAgent is bootstrapped only if the service user is currently
   logged in (uncommon at install time); otherwise `RunAtLoad=true`
   means it loads automatically the next time the operator FUS-es into
   the service account.

## What the operator still has to do post-install

Two FUS-to-service-account clicks once, ever:

1. **Full Disk Access** for `OpenClawRelay.app/Contents/MacOS/OpenClawRelay`
   so the relay can read `~/Library/Messages/chat.db`. System Settings
   → Privacy & Security → Full Disk Access → drag the binary in.
2. **Automation: Messages.app** — fires the first time the relay tries
   to send via osascript. Click *Allow* on
   *"OpenClaw Relay wants to control Messages.app"*.

These TCC grants are per-user and must be granted under the service
user's session. Everything else (Calendar, Contacts, Reminders, Apple
Events for Notes — all the bridge's TCC dependencies on the *main* user
side) is prompted automatically the first time the bridge attempts each
API and shows under the brand "MacOS Bridge for OpenClaw".

## Files

| File | Role |
| --- | --- |
| `Distribution.xml` | productbuild distribution manifest. References the two component pkgs (`me.lopes.openclaw.bridge.pkg`, `me.lopes.openclaw.relay.pkg`), pins minimum macOS 14, locks to arm64. `customize="never"` hides the package selector — both components ship as a unit. |
| `scripts/postinstall` | Heavy-lifter described above. Runs as root, surfaces failures via `osascript display alert` under the console user's session so the operator sees a useful error rather than Installer's generic one. |
| `build-pkg.sh` | `pkgbuild` (×2 components) → `productbuild` → `productsign` → `notarytool` → `stapler`. `SKIP_SIGN=1` and `SKIP_NOTARIZE=1` flags mirror the bundle scripts. |
| `dist/` | Final pkg output. Not checked in. |
| `build/` | pkgbuild + productbuild intermediates. Not checked in. |

## Prerequisites

```
bundle/bridge/build.sh    # produces bundle/bridge/dist/OpenClawBridge.app
bundle/relay/build.sh     # produces bundle/relay/dist/OpenClawRelay.app
```

Both must exist before `installer/build-pkg.sh` runs. Both should be
Developer-ID-Application signed (notarized too is recommended — the pkg's
notarization validates the inner signatures regardless).

## Required Apple credentials

Distinct from the `.app` bundle build:

- **Developer ID Installer cert** — separate cert from the *Application*
  cert used by `bundle/{bridge,relay}/build.sh`. Obtain it at
  developer.apple.com → Account → Certificates, Identifiers & Profiles
  → Certificates → "+" → *Developer ID Installer*. Generate a CSR via
  Keychain Access → Certificate Assistant → Request a Certificate from
  a Certificate Authority, upload it, download the issued cert,
  double-click to install in your login keychain.
- **Notarization profile** — the same `MacOs-OpenClaw.Notary` profile
  used by the `.app` builds. notarytool happily signs both .app and
  .pkg submissions with the same credentials.

## Build flow

```
$ export TEAM_ID=283UY8S778
$ export DEV_ID_INSTALLER_IDENTITY="Developer ID Installer: Giuseppe Lopes (283UY8S778)"
$ export NOTARY_PROFILE=MacOs-OpenClaw.Notary
$ installer/build-pkg.sh         # ~3 minutes (mostly notarization wait)
```

For composition iteration without burning notarization submissions:

```
$ SKIP_SIGN=1 installer/build-pkg.sh
$ pkgutil --expand installer/dist/MacOSBridgeForOpenClaw.pkg /tmp/pkg-expand
$ ls /tmp/pkg-expand
```

After both pass: `installer/dist/MacOSBridgeForOpenClaw.pkg` is ready
to ship. Double-click installs the entire stack.

## How to test the postinstall script in isolation

The `pkgutil --expand` output contains `Scripts/postinstall` exactly as
shipped. To dry-run without actually installing:

```
$ sudo bash -x /tmp/pkg-expand/Scripts/postinstall
```

(Be careful — this writes real files. Roll back with the cleanup
section below.)

## Uninstall / cleanup

The pkg does not include an uninstaller. To roll back manually:

```
# Stop launchd jobs
launchctl bootout gui/$(id -u)/me.lopes.openclaw.bridge 2>/dev/null
sudo launchctl bootout gui/$(id -u <service_user>)/me.lopes.openclaw.relay.<service_user> 2>/dev/null

# Remove LaunchAgents
rm -f ~/Library/LaunchAgents/me.lopes.openclaw.bridge.plist
sudo rm -f /Users/<service_user>/Library/LaunchAgents/me.lopes.openclaw.relay.*.plist

# Remove .app bundles
sudo rm -rf /Applications/OpenClawBridge.app /Applications/OpenClawRelay.app

# Remove config
sudo rm -rf "/Library/Application Support/OpenClaw"

# Forget the pkg receipts
sudo pkgutil --forget me.lopes.openclaw.bridge.pkg
sudo pkgutil --forget me.lopes.openclaw.relay.pkg
```

Keychain entries (relay token, bridge tokens, OpenRouter key, etc.)
stay — those are operator data, not artefacts of the install.

## Caveats

- **No CI yet.** Same as the bundle scripts — needs operator's signing
  identity and notarytool credentials.
- **Service user is asked once, never again.** If you mistype, re-run
  the pkg installer (idempotent — it overwrites the LaunchAgents).
- **Account-agnostic, agent-agnostic relay bundle.** The relay
  bundle (`me.lopes.openclaw.relay`) sets `AGENT_NAME=agent` directly
  in the bundled LaunchAgent's `EnvironmentVariables`; the keychain
  actor key (`relay.<account>`) is resolved at runtime from
  `getpass.getuser()`. One signed binary works for any macOS user
  account that registers it. The runtime config validates `AGENT_NAME`
  against `^[a-z][a-z0-9_]{0,31}$` (see
  `relays/imessage/src/relay/config.py`).
