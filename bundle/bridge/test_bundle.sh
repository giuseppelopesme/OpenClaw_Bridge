#!/usr/bin/env bash
# Smoke-test the built OpenClawBridge.app.
#
# Run after bundle/bridge/build.sh. Verifies every checkable property of
# the bundle that does NOT require executing it. Mirrors
# bundle/relay/test_bundle.sh — see that file for the rationale behind
# each check.
#
# When build.sh ran with SKIP_SIGN=1, the codesign / spctl / stapler
# checks below will fail by design — pass SKIP_SIGN_CHECKS=1 here to
# only assert structural + plist properties. Useful while iterating on
# the spec without burning notarization submissions.

set -euo pipefail

bundle_dir="$(cd "$(dirname "$0")" && pwd)"
app_path="${bundle_dir}/dist/OpenClawBridge.app"
skip_sign_checks="${SKIP_SIGN_CHECKS:-0}"

if [[ ! -d "${app_path}" ]]; then
    echo "FAIL: ${app_path} not found — run build.sh first" >&2
    exit 1
fi

fail() {
    echo "FAIL: $*" >&2
    exit 1
}

# ---- structural checks ----------------------------------------------

[[ -x "${app_path}/Contents/MacOS/OpenClawBridge" ]] \
    || fail "Contents/MacOS/OpenClawBridge missing or not executable"

[[ -f "${app_path}/Contents/Info.plist" ]] \
    || fail "Contents/Info.plist missing"

[[ -f "${app_path}/Contents/Library/LaunchAgents/me.lopes.openclaw.bridge.plist" ]] \
    || fail "bundled LaunchAgent plist missing"

# Bundled redis-server — supervisor spawns it as the first child.
# Pkg installs are useless without it; missing this is a build-time bug.
[[ -x "${app_path}/Contents/MacOS/redis-server" ]] \
    || fail "bundled redis-server missing or not executable"
/usr/bin/file "${app_path}/Contents/MacOS/redis-server" | grep -q "arm64" \
    || fail "bundled redis-server is not arm64"

# ---- Info.plist values ---------------------------------------------

bundle_id="$(plutil -extract CFBundleIdentifier raw -o - "${app_path}/Contents/Info.plist")"
[[ "${bundle_id}" == "me.lopes.openclaw.bridge" ]] \
    || fail "CFBundleIdentifier is '${bundle_id}', expected me.lopes.openclaw.bridge"

display_name="$(plutil -extract CFBundleDisplayName raw -o - "${app_path}/Contents/Info.plist")"
[[ "${display_name}" == "MacOS Bridge for OpenClaw" ]] \
    || fail "CFBundleDisplayName is '${display_name}', expected 'MacOS Bridge for OpenClaw'"

ls_ui="$(plutil -extract LSUIElement raw -o - "${app_path}/Contents/Info.plist")"
[[ "${ls_ui}" == "true" || "${ls_ui}" == "1" ]] \
    || fail "LSUIElement is '${ls_ui}', expected true (background app)"

# Every TCC purpose string the bridge depends on must be present and non-empty.
for key in NSCalendarsUsageDescription NSContactsUsageDescription \
           NSRemindersUsageDescription NSAppleEventsUsageDescription; do
    val="$(plutil -extract "${key}" raw -o - "${app_path}/Contents/Info.plist" 2>/dev/null || true)"
    [[ -n "${val}" ]] || fail "${key} is empty — first TCC prompt for that API would show no rationale"
done

# ---- multi-mode binary smoke check ----------------------------------

# The frozen binary is multi-mode (see bundle/bridge/entry.py). We can
# verify it boots and recognises an unknown mode without spinning up a
# real bridge — passing a junk mode prints to stderr and exits 2.
unknown_out=$("${app_path}/Contents/MacOS/OpenClawBridge" __no_such_mode__ 2>&1 || true)
echo "${unknown_out}" | grep -q "unknown mode" \
    || fail "binary does not recognise the multi-mode dispatch (unknown-mode case): ${unknown_out}"

if [[ "${skip_sign_checks}" == "1" ]]; then
    echo "OK (structural only, skipping sign + spctl + stapler):"
    echo "    ${app_path}"
    echo "    bundle id: ${bundle_id}"
    echo "    display name: ${display_name}"
    echo "    LSUIElement: ${ls_ui}"
    exit 0
fi

# ---- code-signing checks --------------------------------------------

verify_out="$(codesign --verify --deep --strict --verbose=2 "${app_path}" 2>&1)"
echo "${verify_out}" | grep -q "valid on disk" \
    || fail "codesign --verify did not report 'valid on disk': ${verify_out}"

sig_info="$(codesign -dvv "${app_path}" 2>&1)"
echo "${sig_info}" | grep -q "flags=0x10000(runtime)" \
    || fail "hardened runtime not enabled (codesign --options runtime missing?)"
echo "${sig_info}" | grep -q "Authority=Developer ID Application:" \
    || fail "not signed with a Developer ID Application certificate"

# ---- entitlements check ---------------------------------------------

ent="$(codesign -d --entitlements - --xml "${app_path}" 2>/dev/null)"
echo "${ent}" | grep -q "com.apple.security.automation.apple-events" \
    || fail "automation.apple-events entitlement missing"
echo "${ent}" | grep -q "com.apple.security.cs.allow-jit" \
    || fail "cs.allow-jit entitlement missing (PyInstaller bootloader needs it)"

# ---- Gatekeeper (spctl) ---------------------------------------------

spctl_out="$(spctl --assess --type exec --verbose=4 "${app_path}" 2>&1)"
echo "${spctl_out}" | grep -q "accepted" \
    || fail "spctl rejected the bundle: ${spctl_out}"
echo "${spctl_out}" | grep -q "source=Notarized Developer ID" \
    || fail "spctl source is not 'Notarized Developer ID' — bundle not stapled? ${spctl_out}"

# ---- stapler check --------------------------------------------------

xcrun stapler validate "${app_path}" >/dev/null \
    || fail "stapler validation failed"

echo "OK: ${app_path}"
echo "    bundle id: ${bundle_id}"
echo "    display name: ${display_name}"
echo "    LSUIElement: ${ls_ui}"
echo "    spctl: $(echo "${spctl_out}" | head -1)"
