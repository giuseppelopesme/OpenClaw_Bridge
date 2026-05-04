#!/usr/bin/env bash
# One-shot bootstrap for the clu user account (run AS clu, not giuseppelopes).
#
# Usage:
#     bash scripts/setup-clu-account.sh <relay-token-plaintext> [<app-path>]
#
# Pre-requisites (operator-side, before invoking):
#
#  1. Mint the relay token on the bridge host (giuseppelopes):
#         scripts/mint-token.py --actor relay.clu --scopes imessage:relay
#     Capture the plaintext — pass it as argument 1 below.
#
#  2. Build OpenClawRelay.app on giuseppelopes via:
#         bundle/relay/build.sh
#     Then copy the resulting .app to a path readable by clu, e.g.:
#         sudo cp -R bundle/relay/dist/OpenClawRelay.app /Applications/
#     /Applications/OpenClawRelay.app is the default; pass an alternate
#     path as argument 2 if needed (~/Applications also works).
#
# This script runs AS clu and:
#
#   a. Stores the relay token in clu's login keychain.
#   b. Verifies OpenClawRelay.app is present, signed, and notarized.
#   c. Materialises ~/Library/LaunchAgents/com.giuseppelopesme.openclaw.relay.clu.plist
#      from the LaunchAgent template bundled inside the .app, substituting
#      __APP_PATH__ and __LOG_DIR__ for the real install paths.
#   d. Bootstraps the launchd job in clu's GUI domain.
#
# Manual follow-up (cannot be automated — both grants prompt the user):
#
#   * Full Disk Access for the bundle's Contents/MacOS/OpenClawRelay binary,
#     so the relay can read ~/Library/Messages/chat.db.
#   * Automation control of Messages.app — fires the first time the relay
#     attempts to send; click Allow.
#
# Idempotent: re-running fast-forwards the keychain entry, regenerates the
# LaunchAgent plist, and reloads the launchd job.

set -euo pipefail

if [[ "$(id -un)" != "clu" ]]; then
    echo "ERROR: run this AS the clu user, not $(id -un)." >&2
    echo "Try: sudo su - clu" >&2
    exit 2
fi

if [[ $# -lt 1 ]]; then
    echo "usage: $0 <relay-token-plaintext> [<app-path>]" >&2
    echo "       (default app-path: /Applications/OpenClawRelay.app)" >&2
    exit 2
fi

token="$1"
app_path="${2:-/Applications/OpenClawRelay.app}"
log_dir="${HOME}/.openclaw"
launch_agent="${HOME}/Library/LaunchAgents/com.giuseppelopesme.openclaw.relay.clu.plist"
bundled_template="${app_path}/Contents/Library/LaunchAgents/com.giuseppelopesme.openclaw.relay.clu.plist"

# ---- 1. relay token in clu's login keychain --------------------------

echo "==> 1. storing relay.clu token in clu's login keychain"
payload="{\"token\":\"${token}\",\"scopes\":[\"imessage:relay\"]}"
# -U replaces any existing item under the same (service, account).
security add-generic-password \
    -U \
    -a relay.clu \
    -s com.giuseppelopesme.openclaw.bridge \
    -w "${payload}"

# ---- 2. verify OpenClawRelay.app is present + trusted ---------------

echo "==> 2. verifying ${app_path}"
if [[ ! -d "${app_path}" ]]; then
    echo "ERROR: ${app_path} not found." >&2
    echo "       Build it on giuseppelopes via bundle/relay/build.sh, then:" >&2
    echo "         sudo cp -R bundle/relay/dist/OpenClawRelay.app /Applications/" >&2
    exit 2
fi
if [[ ! -f "${bundled_template}" ]]; then
    echo "ERROR: bundled LaunchAgent template missing at ${bundled_template}" >&2
    echo "       The .app at ${app_path} appears malformed." >&2
    exit 2
fi
# Gatekeeper check — refuses to run an un-notarized or tampered bundle.
if ! spctl --assess --type exec "${app_path}" >/dev/null 2>&1; then
    echo "ERROR: ${app_path} is not accepted by Gatekeeper." >&2
    echo "       Run bundle/relay/test_bundle.sh on giuseppelopes to diagnose." >&2
    exit 2
fi

# ---- 3. materialise LaunchAgent plist -------------------------------

echo "==> 3. installing ${launch_agent}"
mkdir -p "$(dirname "${launch_agent}")" "${log_dir}"
# Substitute placeholders. macOS sed can be picky with `/` in replacement
# strings; we use a `|` delimiter and rely on the absence of `|` in paths.
sed \
    -e "s|__APP_PATH__|${app_path}|g" \
    -e "s|__LOG_DIR__|${log_dir}|g" \
    "${bundled_template}" \
    > "${launch_agent}"
plutil -lint "${launch_agent}"

# ---- 4. bootstrap launchd job ---------------------------------------

echo "==> 4. bootstrapping launchd job"
# Bootout first (if loaded) so we get a clean reload.
launchctl bootout "gui/$(id -u)/com.giuseppelopesme.openclaw.relay.clu" 2>/dev/null || true
launchctl bootstrap "gui/$(id -u)" "${launch_agent}"

sleep 2
echo
echo "==> done. status:"
launchctl list | grep openclaw || true
echo
echo "Next manual steps (cannot be automated — System Settings UI):"
echo
echo "  * Full Disk Access — System Settings > Privacy & Security >"
echo "    Full Disk Access > '+' > navigate to:"
echo "    ${app_path}/Contents/MacOS/OpenClawRelay"
echo "    (drag from Finder if Settings refuses to enter the .app)"
echo
echo "  * Automation: Messages.app — fires automatically on first send."
echo "    Click Allow when 'OpenClawRelay wants to control Messages.app'"
echo "    appears."
echo
echo "Tail logs with:"
echo "    tail -f ${log_dir}/relay.clu.err.log"
