#!/usr/bin/env bash
# One-shot bootstrap for a relay service account (run AS the service
# account, not the bridge host's main user).
#
# Usage:
#     bash scripts/setup-relay-account.sh <relay-token-plaintext> [<app-path>]
#
# Pre-requisites (operator-side, before invoking):
#
#  1. Mint the relay token on the bridge host (whoever runs the bridge):
#         scripts/mint-token.py --actor relay.<this-account> \
#             --scopes imessage:relay
#     Capture the plaintext — pass it as argument 1 below.
#
#  2. Build OpenClawRelay.app on the bridge host via:
#         bundle/relay/build.sh
#     Then copy the resulting .app to a path readable by this account,
#     e.g.:
#         sudo cp -R bundle/relay/dist/OpenClawRelay.app /Applications/
#     /Applications/OpenClawRelay.app is the default; pass an alternate
#     path as argument 2 if needed (~/Applications also works).
#
# This script runs AS the relay's service account and:
#
#   a. Stores the relay token in this account's login keychain.
#   b. Verifies OpenClawRelay.app is present, signed, and notarized.
#   c. Registers the bundled LaunchAgent via SMAppService — no plist
#      copying to ~/Library/LaunchAgents/. The .app's bundled template
#      sets AGENT_NAME directly in EnvironmentVariables; no per-account
#      substitution is performed.
#
# Manual follow-up (cannot be automated — both grants prompt the user):
#
#   * Full Disk Access for the bundle's Contents/MacOS/OpenClawRelay binary,
#     so the relay can read ~/Library/Messages/chat.db.
#   * Automation control of Messages.app — fires the first time the relay
#     attempts to send; click Allow.
#
# Idempotent: re-running fast-forwards the keychain entry and re-registers
# the LaunchAgent.

set -euo pipefail

if [[ $# -lt 1 ]]; then
    echo "usage: $0 <relay-token-plaintext> [<app-path>]" >&2
    echo "       (default app-path: /Applications/OpenClawRelay.app)" >&2
    exit 2
fi

token="$1"
app_path="${2:-/Applications/OpenClawRelay.app}"
account="$(id -un)"
register_helper="${app_path}/Contents/MacOS/openclaw-register"

# ---- 1. relay token in this account's login keychain ----------------

echo "==> 1. storing relay.${account} token in ${account}'s login keychain"
payload="{\"token\":\"${token}\",\"scopes\":[\"imessage:relay\"]}"
# -U replaces any existing item under the same (service, account); -A
# allows all apps to read it without firing macOS's "wants to access"
# prompt at runtime.
security add-generic-password \
    -U \
    -A \
    -a "relay.${account}" \
    -s me.lopes.openclaw.bridge \
    -w "${payload}"

# ---- 2. verify OpenClawRelay.app is present + trusted ---------------

echo "==> 2. verifying ${app_path}"
if [[ ! -d "${app_path}" ]]; then
    echo "ERROR: ${app_path} not found." >&2
    echo "       Build it on the bridge host via bundle/relay/build.sh, then:" >&2
    echo "         sudo cp -R bundle/relay/dist/OpenClawRelay.app /Applications/" >&2
    exit 2
fi
if [[ ! -x "${register_helper}" ]]; then
    echo "ERROR: SMAppService register helper missing at ${register_helper}" >&2
    echo "       The .app at ${app_path} appears malformed." >&2
    exit 2
fi
# Gatekeeper check — refuses to run an un-notarized or tampered bundle.
if ! spctl --assess --type exec "${app_path}" >/dev/null 2>&1; then
    echo "ERROR: ${app_path} is not accepted by Gatekeeper." >&2
    echo "       Run bundle/relay/test_bundle.sh on the bridge host to diagnose." >&2
    exit 2
fi

# ---- 3. SMAppService register the LaunchAgent -----------------------

echo "==> 3. registering LaunchAgent via SMAppService"
# SMAppService.agent(plistName:) takes the BARE filename (not a path).
# The bundled plist sets AGENT_NAME in EnvironmentVariables already.
"${register_helper}" register me.lopes.openclaw.relay.plist

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
echo "    tail -f ~/.openclaw/relay.${account}.err.log"
