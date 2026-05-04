#!/usr/bin/env bash
# Smoke-test the built OpenClawRelay.app.
#
# Run after bundle/relay/build.sh. Verifies every checkable property of
# the bundle that does NOT require executing it (executing is part of
# the operator-side install on clu's desktop). Each check exits non-zero
# on failure, with a one-line diagnostic so the build log is grep-able.

set -euo pipefail

bundle_dir="$(cd "$(dirname "$0")" && pwd)"
app_path="${bundle_dir}/dist/OpenClawRelay.app"

if [[ ! -d "${app_path}" ]]; then
    echo "FAIL: ${app_path} not found — run build.sh first" >&2
    exit 1
fi

fail() {
    echo "FAIL: $*" >&2
    exit 1
}

# ---- structural checks ----------------------------------------------

[[ -x "${app_path}/Contents/MacOS/OpenClawRelay" ]] \
    || fail "Contents/MacOS/OpenClawRelay missing or not executable"

[[ -f "${app_path}/Contents/Info.plist" ]] \
    || fail "Contents/Info.plist missing"

[[ -f "${app_path}/Contents/Library/LaunchAgents/com.giuseppelopesme.openclaw.relay.clu.plist" ]] \
    || fail "bundled LaunchAgent plist missing"

# ---- Info.plist values ---------------------------------------------

bundle_id="$(plutil -extract CFBundleIdentifier raw -o - "${app_path}/Contents/Info.plist")"
[[ "${bundle_id}" == "com.giuseppelopesme.openclaw.relay.clu" ]] \
    || fail "CFBundleIdentifier is '${bundle_id}', expected com.giuseppelopesme.openclaw.relay.clu"

# LSUIElement — plutil prints "true" or "1" depending on macOS version.
ls_ui="$(plutil -extract LSUIElement raw -o - "${app_path}/Contents/Info.plist")"
[[ "${ls_ui}" == "true" || "${ls_ui}" == "1" ]] \
    || fail "LSUIElement is '${ls_ui}', expected true (background app)"

usage="$(plutil -extract NSAppleEventsUsageDescription raw -o - "${app_path}/Contents/Info.plist")"
[[ -n "${usage}" ]] \
    || fail "NSAppleEventsUsageDescription is empty — Automation prompt would show no rationale"

# ---- code-signing checks --------------------------------------------

# Capture output first then grep — `grep -q` closes its stdin on first
# match, codesign dies with SIGPIPE (141), and `pipefail` would treat
# that as a pipeline failure even though the verify itself succeeded.
verify_out="$(codesign --verify --deep --strict --verbose=2 "${app_path}" 2>&1)"
echo "${verify_out}" | grep -q "valid on disk" \
    || fail "codesign --verify did not report 'valid on disk': ${verify_out}"

# Hardened runtime + Developer ID signing — both required for notarization.
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

# After notarization + stapling, this prints "accepted ... source=Notarized
# Developer ID". Pre-notarization (during local dev) it would say
# "rejected" — fail loudly so we don't ship an un-notarized bundle.
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
echo "    LSUIElement: ${ls_ui}"
echo "    spctl: $(echo "${spctl_out}" | head -1)"
