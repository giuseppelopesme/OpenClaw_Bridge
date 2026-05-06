#!/usr/bin/env bash
# Full uninstall + cleanup for OpenClaw, both users (main + service).
#
# Removes:
#   - Both .app bundles from /Applications
#   - LaunchAgent plists from both users' ~/Library/LaunchAgents/
#   - launchd jobs (bootout) under both users' gui domains
#   - /Library/Application Support/OpenClaw
#   - ~/.openclaw on both users (logs, state, idempotency DB, telemetry DB)
#   - Pkg receipts (pkgutil --forget) for both component pkgs
#   - TCC grants for our two bundle identifiers (Calendar, Contacts,
#     Reminders, AppleEvents, Accessibility, Full Disk Access)
#
# Does NOT remove:
#   - macOS user accounts (the service user account stays)
#   - Keychain tokens (relay token in the service user's keychain, plus
#     bridge tokens in the main user's keychain stay — they're useful
#     state, not artefacts of the install)
#   - Redis password in main user's keychain
#
# Usage (from the main user account, with sudo):
#     sudo bash installer/uninstall.sh
#
# Run as root because removing /Applications and /Library/Application
# Support requires it. The script reads SUDO_USER to find the human's
# UID for tccutil and bootout calls.

set -euo pipefail

# ---- preflight ------------------------------------------------------

if [[ "$(id -u)" -ne 0 ]]; then
    echo "ERROR: must be run with sudo (need root to remove /Applications and /Library)" >&2
    exit 2
fi

main_user="${SUDO_USER:-}"
if [[ -z "${main_user}" || "${main_user}" == "root" ]]; then
    echo "ERROR: SUDO_USER not set; run as: sudo bash installer/uninstall.sh" >&2
    exit 2
fi

main_uid="$(id -u "${main_user}")"
main_home="$(/usr/bin/dscl . -read "/Users/${main_user}" NFSHomeDirectory \
    | awk '{print $2}')"

# Read the chosen service user from the install's config.json. If config
# is missing (manual cleanup), enumerate human-ish accounts and offer them.
config_json="/Library/Application Support/OpenClaw/config.json"
service_user=""
if [[ -f "${config_json}" ]]; then
    service_user="$(/usr/bin/python3 -c "
import json, sys
with open('${config_json}') as f:
    print(json.load(f).get('service_user', ''))
" 2>/dev/null || true)"
fi
if [[ -z "${service_user}" ]]; then
    echo "WARN: no config.json — falling back to first non-main UID >= 501 user."
    service_user="$(
        /usr/bin/dscl . -list /Users UniqueID \
        | awk -v main="${main_user}" '$2 >= 501 && $1 != main && $1 !~ /^_/ { print $1; exit }'
    )"
fi
service_uid="$(id -u "${service_user}" 2>/dev/null || true)"
service_home=""
if [[ -n "${service_uid}" ]]; then
    service_home="$(/usr/bin/dscl . -read "/Users/${service_user}" NFSHomeDirectory \
        | awk '{print $2}')"
fi

echo "==> uninstalling OpenClaw"
echo "    main user:    ${main_user} (uid=${main_uid}, home=${main_home})"
echo "    service user: ${service_user:-<unknown>} (uid=${service_uid:-<unknown>}, home=${service_home:-<unknown>})"
echo

# ---- 1. SMAppService unregister + bootout LaunchAgents --------------

echo "==> 1. unregister SMAppService agents (modern install path)"
bridge_register="/Applications/OpenClawBridge.app/Contents/MacOS/openclaw-register"
relay_register="/Applications/OpenClawRelay.app/Contents/MacOS/openclaw-register"
# SMAppService.agent(plistName:) takes the bare filename, not a path.
if [[ -x "${bridge_register}" ]]; then
    launchctl asuser "${main_uid}" \
        "${bridge_register}" unregister \
        "me.lopes.openclaw.bridge.plist" \
        2>/dev/null && echo "    bridge: unregistered" || echo "    bridge: nothing to unregister"
fi
if [[ -x "${relay_register}" && -n "${service_uid}" ]]; then
    launchctl asuser "${service_uid}" \
        "${relay_register}" unregister \
        "me.lopes.openclaw.relay.plist" \
        2>/dev/null && echo "    relay: unregistered" || echo "    relay: nothing to unregister (or service user not in Aqua session)"
fi

echo "==> 1b. bootout legacy LaunchAgents (pre-SMAppService installs)"
launchctl bootout "gui/${main_uid}/me.lopes.openclaw.bridge" 2>/dev/null \
    && echo "    bridge LA: bootout OK" \
    || echo "    bridge LA: not loaded"

if [[ -n "${service_uid}" && -n "${service_user}" ]]; then
    launchctl bootout "gui/${service_uid}/me.lopes.openclaw.relay" 2>/dev/null \
        && echo "    relay LA: bootout OK" \
        || true
    launchctl bootout "gui/${service_uid}/me.lopes.openclaw.relay.${service_user}" 2>/dev/null \
        && echo "    relay LA (.${service_user}): bootout OK" \
        || echo "    relay LA: not loaded (or service user not in Aqua session)"
fi

# ---- 2. remove legacy LaunchAgent plists ----------------------------

echo "==> 2. remove legacy LaunchAgent plist files (if any pre-SMAppService leftovers)"
rm -fv "${main_home}/Library/LaunchAgents/me.lopes.openclaw.bridge.plist" 2>/dev/null || true
if [[ -n "${service_home}" ]]; then
    rm -fv "${service_home}/Library/LaunchAgents/me.lopes.openclaw.relay."*".plist" 2>/dev/null || true
fi

# ---- 3. remove .app bundles -----------------------------------------

echo "==> 3. remove .app bundles from /Applications"
rm -rfv /Applications/OpenClawBridge.app 2>/dev/null || true
rm -rfv /Applications/OpenClawRelay.app  2>/dev/null || true

# ---- 4. remove /Library/Application Support/OpenClaw ----------------

echo "==> 4. remove /Library/Application Support/OpenClaw"
rm -rfv "/Library/Application Support/OpenClaw" 2>/dev/null || true

# ---- 5. remove per-user state dirs (logs, DBs) ----------------------

echo "==> 5. remove per-user .openclaw dirs"
rm -rfv "${main_home}/.openclaw" 2>/dev/null || true
if [[ -n "${service_home}" ]]; then
    rm -rfv "${service_home}/.openclaw" 2>/dev/null || true
fi

# ---- 6. forget pkg receipts -----------------------------------------

echo "==> 6. forget pkg receipts"
for pkg in me.lopes.openclaw.bridge.pkg me.lopes.openclaw.relay.pkg; do
    pkgutil --forget "${pkg}" 2>/dev/null \
        && echo "    forgot ${pkg}" \
        || echo "    ${pkg} not registered"
done

# ---- 7. tccutil reset for our bundle identifiers --------------------

# tccutil's reset is per-user. It needs to run inside each user's
# environment to hit their TCC database. `sudo -u <user>` swaps to that
# user's context for the reset.
#
# CRITICAL: every reset below MUST include the bundle identifier. An
# unscoped `tccutil reset <service>` wipes EVERY app's grants for that
# service in the user's TCC database — that's how earlier versions of
# this script accidentally erased the operator's unrelated Accessibility
# grants every time they reinstalled. Targeted resets only remove our
# bundle's row, leaving every other app's grants intact.
echo "==> 7. tccutil reset (per-user, per-bundle — never unscoped)"
for service in Calendar Contacts Reminders AppleEvents Accessibility \
               SystemPolicyAllFiles SystemPolicyDocumentsFolder \
               SystemPolicyDownloadsFolder; do
    for bid in me.lopes.openclaw.bridge me.lopes.openclaw.relay; do
        # Main user
        sudo -u "${main_user}" tccutil reset "${service}" "${bid}" \
            2>/dev/null \
            && echo "    [${main_user}] reset ${service} for ${bid}" \
            || true
        # Service user (if available)
        if [[ -n "${service_user}" && "${service_user}" != "${main_user}" ]]; then
            sudo -u "${service_user}" tccutil reset "${service}" "${bid}" \
                2>/dev/null \
                && echo "    [${service_user}] reset ${service} for ${bid}" \
                || true
        fi
    done
done

# Resolve placeholders for the keychain-wipe hint. We never hardcode
# specific account names (e.g. agent or service-user names) — installs
# vary, and the relay account is whatever the operator picked at install
# time. If we don't know the service user, the hint shows a placeholder
# the operator must fill in themselves.
hint_service_user="${service_user:-<service-user-account>}"

echo
echo "==> uninstall complete."
echo
echo "If you also want to wipe Keychain entries (rarely needed; tokens"
echo "are useful state to preserve across reinstalls), run the commands"
echo "below. The bridge keychain holds entries for every actor it talks"
echo "to (the agent brain, provider tokens, the manifest); the service"
echo "user's keychain holds only the relay token for that account."
echo
echo "    # main user keychain — wipe every OpenClaw entry"
echo "    while IFS= read -r account; do"
echo "        security delete-generic-password \\"
echo "            -s me.lopes.openclaw.bridge -a \"\$account\" 2>/dev/null"
echo "    done < <("
echo "        security dump-keychain \"${main_home}/Library/Keychains/login.keychain-db\" \\"
echo "            | awk -F'\"' '/\"svce\"<blob>=\"me.lopes.openclaw.bridge\"/{f=1} f && /\"acct\"<blob>=/ {print \$2; f=0}'"
echo "    )"
echo
echo "    # service user keychain (run as ${hint_service_user})"
echo "    security delete-generic-password \\"
echo "        -s me.lopes.openclaw.bridge -a relay.${hint_service_user}"
