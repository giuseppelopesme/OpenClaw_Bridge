#!/usr/bin/env bash
# Build, sign, notarize, and staple OpenClawRelay.app.
#
# Usage:
#     bundle/relay/build.sh
#
# Required env (set by the operator before invoking; build.sh will fail
# fast if anything is missing):
#
#     TEAM_ID            Apple Developer team identifier (10 chars).
#     DEV_ID_IDENTITY    Full "Developer ID Application: <Name> (<TEAM_ID>)"
#                        string as it appears in `security find-identity`.
#                        Example: "Developer ID Application: Giuseppe Lopes (283UY8S778)"
#     NOTARY_PROFILE     Name of the notarytool keychain profile created
#                        with `xcrun notarytool store-credentials`.
#                        Convention: MacOs-OpenClaw.Notary.
#
# Idempotent: re-running cleans dist/ and build/ and rebuilds from
# source. The notarization request is fresh each time (Apple does not
# de-dup; a unique request_id is returned per submission).

set -euo pipefail

# ---- locate ourselves ------------------------------------------------

bundle_dir="$(cd "$(dirname "$0")" && pwd)"
repo_root="$(cd "${bundle_dir}/../.." && pwd)"

# ---- preflight -------------------------------------------------------

: "${TEAM_ID:?TEAM_ID env var required (10-char Apple Developer team id)}"
: "${DEV_ID_IDENTITY:?DEV_ID_IDENTITY env var required (full \"Developer ID Application: ...\" string)}"
: "${NOTARY_PROFILE:?NOTARY_PROFILE env var required (e.g. MacOs-OpenClaw.Notary)}"

# Length-check TEAM_ID — Apple's team IDs are uppercase alphanumerics, 10 chars.
if [[ ! "${TEAM_ID}" =~ ^[A-Z0-9]{10}$ ]]; then
    echo "ERROR: TEAM_ID does not look like an Apple Developer team id (10 alphanumerics): ${TEAM_ID}" >&2
    exit 2
fi

if ! security find-identity -v -p codesigning | grep -q -F "${DEV_ID_IDENTITY}"; then
    echo "ERROR: '${DEV_ID_IDENTITY}' not found in login keychain." >&2
    echo "       Verify with: security find-identity -v -p codesigning" >&2
    exit 2
fi

if ! xcrun notarytool history --keychain-profile "${NOTARY_PROFILE}" >/dev/null 2>&1; then
    echo "ERROR: notarytool profile '${NOTARY_PROFILE}' is not authenticated." >&2
    echo "       Create it with: xcrun notarytool store-credentials ${NOTARY_PROFILE} \\" >&2
    echo "         --apple-id <your-apple-id> --team-id ${TEAM_ID} --password <app-specific-password>" >&2
    exit 2
fi

# ---- versioning ------------------------------------------------------

# Read the version from relays/imessage/pyproject.toml so the .app's
# CFBundleVersion always tracks the package version.
relay_version="$(
    awk -F '"' '/^version *= *"/ { print $2; exit }' \
        "${repo_root}/relays/imessage/pyproject.toml"
)"
if [[ -z "${relay_version}" ]]; then
    echo "ERROR: could not parse version from relays/imessage/pyproject.toml" >&2
    exit 2
fi
echo "==> building OpenClawRelay.app v${relay_version}"

# ---- clean -----------------------------------------------------------

cd "${repo_root}"
rm -rf "${bundle_dir}/dist" "${bundle_dir}/build"

# ---- pyinstaller -----------------------------------------------------

echo "==> running PyInstaller"
# `--workpath` and `--distpath` keep build artefacts inside bundle/relay/
# rather than the repo root. `--clean` clears PyInstaller's own cache.
uv run --no-sync pyinstaller \
    --clean \
    --noconfirm \
    --workpath "${bundle_dir}/build" \
    --distpath "${bundle_dir}/dist" \
    "${bundle_dir}/pyinstaller.spec"

app_path="${bundle_dir}/dist/OpenClawRelay.app"
if [[ ! -d "${app_path}" ]]; then
    echo "ERROR: PyInstaller did not produce ${app_path}" >&2
    exit 1
fi

# ---- inject Info.plist + bundled LaunchAgent -------------------------

echo "==> injecting Info.plist (version=${relay_version})"
sed "s/__VERSION__/${relay_version}/g" \
    "${bundle_dir}/Info.plist.template" \
    > "${app_path}/Contents/Info.plist"
plutil -lint "${app_path}/Contents/Info.plist"

echo "==> compiling SMAppService helper (openclaw-register) into Contents/MacOS/"
# Same helper as Bridge.app — see bundle/bridge/build.sh for rationale.
xcrun swiftc \
    -O \
    -target arm64-apple-macos14.0 \
    -framework ServiceManagement \
    -o "${app_path}/Contents/MacOS/openclaw-register" \
    "${repo_root}/bundle/openclaw-register.swift"

echo "==> bundling LaunchAgent template into Contents/Library/LaunchAgents/"
mkdir -p "${app_path}/Contents/Library/LaunchAgents"
cp "${bundle_dir}/launchagent.plist.template" \
    "${app_path}/Contents/Library/LaunchAgents/me.lopes.openclaw.relay.plist"
plutil -lint "${app_path}/Contents/Library/LaunchAgents/me.lopes.openclaw.relay.plist"

# ---- codesign --------------------------------------------------------

echo "==> codesigning (Developer ID, hardened runtime, entitlements)"
# Pass 1: --deep recursive sign of the whole bundle. Every nested
# Mach-O (Frameworks/, MacOS/) gets the right authority + hardened
# runtime + secure timestamp from this pass.
codesign \
    --force \
    --deep \
    --options runtime \
    --timestamp \
    --entitlements "${bundle_dir}/entitlements.plist" \
    --sign "${DEV_ID_IDENTITY}" \
    "${app_path}"

# Pass 2: re-sign openclaw-register with an --identifier that nests
# under the .app's CFBundleIdentifier. Without this, SMAppService
# rejects the .agent(plistName:).register() call because the helper's
# auto-derived identifier ("openclaw-register") is unrelated to the
# bundle it claims to register. See the matching block in
# bundle/bridge/build.sh for the full rationale and the
# `Foundation._GenericObjCError 0` symptom.
echo "==> re-signing openclaw-register with nested bundle identifier"
# Preserve --entitlements on the re-sign so the helper retains the
# parent bundle's entitlement set (cs.disable-library-validation etc).
# See bundle/bridge/build.sh for the dyld / hardened-runtime story
# this matters for.
codesign \
    --force \
    --options runtime \
    --timestamp \
    --identifier "me.lopes.openclaw.relay.openclaw-register" \
    --entitlements "${bundle_dir}/entitlements.plist" \
    --sign "${DEV_ID_IDENTITY}" \
    "${app_path}/Contents/MacOS/openclaw-register"

# Pass 3: refresh the outer bundle's CodeResources so it reflects the
# helper's new identifier.
echo "==> refreshing outer bundle CodeResources"
codesign \
    --force \
    --options runtime \
    --timestamp \
    --entitlements "${bundle_dir}/entitlements.plist" \
    --sign "${DEV_ID_IDENTITY}" \
    "${app_path}"

echo "==> verifying signature"
codesign --verify --deep --strict --verbose=2 "${app_path}"

# ---- notarize --------------------------------------------------------

echo "==> zipping for notarization"
zip_path="${bundle_dir}/dist/OpenClawRelay.zip"
rm -f "${zip_path}"
# `ditto -c -k --sequesterRsrc --keepParent` is Apple's documented way
# to package a .app for notarytool — preserves bundle structure and
# resource forks better than `zip`.
ditto -c -k --sequesterRsrc --keepParent "${app_path}" "${zip_path}"

echo "==> submitting to notarytool (this typically takes 1–3 minutes)"
xcrun notarytool submit \
    "${zip_path}" \
    --keychain-profile "${NOTARY_PROFILE}" \
    --wait

echo "==> stapling notarization ticket"
xcrun stapler staple "${app_path}"
xcrun stapler validate "${app_path}"

# ---- final verification ---------------------------------------------

echo "==> spctl assessment (Gatekeeper)"
spctl --assess --type exec --verbose=4 "${app_path}"

echo
echo "==> SUCCESS: ${app_path}"
echo "    next step: bundle/relay/test_bundle.sh"
