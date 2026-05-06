#!/usr/bin/env bash
# Build, sign, notarize, and staple OpenClawBridge.app.
#
# Mirrors bundle/relay/build.sh. See that script's header for the
# rationale behind each codesign / notarytool step.
#
# Usage:
#     bundle/bridge/build.sh                          # full build (sign + notarize)
#     SKIP_SIGN=1 bundle/bridge/build.sh              # PyInstaller only — useful
#                                                     # for verifying bundle layout
#                                                     # without a Developer ID cert.
#     SKIP_NOTARIZE=1 bundle/bridge/build.sh          # sign but do not notarize —
#                                                     # useful when the notarytool
#                                                     # profile is unavailable.
#                                                     # Bundle won't pass Gatekeeper
#                                                     # for distribution.
#
# Required env (always when not SKIP_SIGN=1):
#
#     TEAM_ID            Apple Developer team identifier (10 chars).
#     DEV_ID_IDENTITY    Full "Developer ID Application: <Name> (<TEAM_ID>)"
#                        as it appears in `security find-identity`.
#
# Required env (only when not SKIP_NOTARIZE=1):
#
#     NOTARY_PROFILE     notarytool keychain profile (e.g. MacOs-OpenClaw.Notary).
#
# Idempotent: re-running cleans dist/ and build/ and rebuilds from
# source. Notarization requests are unique per submission; Apple does
# not de-dup.

set -euo pipefail

# ---- locate ourselves ------------------------------------------------

bundle_dir="$(cd "$(dirname "$0")" && pwd)"
repo_root="$(cd "${bundle_dir}/../.." && pwd)"

# ---- preflight -------------------------------------------------------

skip_sign="${SKIP_SIGN:-0}"
skip_notarize="${SKIP_NOTARIZE:-0}"

if [[ "${skip_sign}" != "1" ]]; then
    : "${TEAM_ID:?TEAM_ID env var required (10-char Apple Developer team id)}"
    : "${DEV_ID_IDENTITY:?DEV_ID_IDENTITY env var required (full \"Developer ID Application: ...\" string)}"

    if [[ ! "${TEAM_ID}" =~ ^[A-Z0-9]{10}$ ]]; then
        echo "ERROR: TEAM_ID does not look like an Apple Developer team id (10 alphanumerics): ${TEAM_ID}" >&2
        exit 2
    fi

    if ! security find-identity -v -p codesigning | grep -q -F "${DEV_ID_IDENTITY}"; then
        echo "ERROR: '${DEV_ID_IDENTITY}' not found in login keychain." >&2
        echo "       Verify with: security find-identity -v -p codesigning" >&2
        exit 2
    fi

    if [[ "${skip_notarize}" != "1" ]]; then
        : "${NOTARY_PROFILE:?NOTARY_PROFILE env var required (e.g. MacOs-OpenClaw.Notary)}"
        if ! xcrun notarytool history --keychain-profile "${NOTARY_PROFILE}" >/dev/null 2>&1; then
            echo "ERROR: notarytool profile '${NOTARY_PROFILE}' is not authenticated." >&2
            echo "       Create it with: xcrun notarytool store-credentials ${NOTARY_PROFILE} \\" >&2
            echo "         --apple-id <your-apple-id> --team-id ${TEAM_ID} --password <app-specific-password>" >&2
            echo "       Or pass SKIP_NOTARIZE=1 to sign without notarizing." >&2
            exit 2
        fi
    fi
fi

# ---- versioning ------------------------------------------------------

# Read the version from bridge/pyproject.toml so the .app's
# CFBundleVersion always tracks the package version.
bridge_version="$(
    awk -F '"' '/^version *= *"/ { print $2; exit }' \
        "${repo_root}/bridge/pyproject.toml"
)"
if [[ -z "${bridge_version}" ]]; then
    echo "ERROR: could not parse version from bridge/pyproject.toml" >&2
    exit 2
fi
echo "==> building OpenClawBridge.app v${bridge_version}"

# ---- clean -----------------------------------------------------------

cd "${repo_root}"
rm -rf "${bundle_dir}/dist" "${bundle_dir}/build"

# ---- pyinstaller -----------------------------------------------------

echo "==> running PyInstaller"
uv run --no-sync pyinstaller \
    --clean \
    --noconfirm \
    --workpath "${bundle_dir}/build" \
    --distpath "${bundle_dir}/dist" \
    "${bundle_dir}/pyinstaller.spec"

app_path="${bundle_dir}/dist/OpenClawBridge.app"
if [[ ! -d "${app_path}" ]]; then
    echo "ERROR: PyInstaller did not produce ${app_path}" >&2
    exit 1
fi

# ---- inject Info.plist + bundled LaunchAgent -------------------------

echo "==> injecting Info.plist (version=${bridge_version})"
sed "s/__VERSION__/${bridge_version}/g" \
    "${bundle_dir}/Info.plist.template" \
    > "${app_path}/Contents/Info.plist"
plutil -lint "${app_path}/Contents/Info.plist"

echo "==> compiling SMAppService helper (openclaw-register) into Contents/MacOS/"
# The helper registers/unregisters the bundled LaunchAgent via the
# modern SMAppService API, so macOS Sequoia's Login Items / Background
# Items panel groups the agent under the .app's CFBundleDisplayName
# (e.g. "MacOS Bridge for OpenClaw") rather than the developer team
# name (e.g. "Giuseppe Lopes"). Source lives at bundle/openclaw-register.swift
# and is compiled fresh into each bundle that ships it.
xcrun swiftc \
    -O \
    -target arm64-apple-macos14.0 \
    -framework ServiceManagement \
    -o "${app_path}/Contents/MacOS/openclaw-register" \
    "${repo_root}/bundle/openclaw-register.swift"

echo "==> bundling redis-server into Contents/MacOS/"
# Copy the Homebrew-installed redis-server into the bundle. This makes
# the .pkg self-contained — fresh installs do not need a separate
# Redis service running on the host. The supervisor (see
# bridge.supervisor._build_default_children) spawns this binary as
# its first child and gates the bridge on its TCP readiness.
#
# Why Contents/MacOS/ and not Contents/Resources/: codesign --deep walks
# Contents/MacOS/, Contents/Frameworks/, and Contents/PlugIns/ when it
# signs the bundle, but NOT Contents/Resources/ (which is for non-code
# data). A Mach-O binary placed in Resources/ is never resigned by the
# bundle's codesign step, so notarization rejects the bundle with
# "The binary is not signed with a valid Developer ID certificate" /
# "The signature does not include a secure timestamp" / "The executable
# does not have the hardened runtime enabled". Putting redis-server in
# MacOS/ lets `codesign --deep` re-sign it under our Developer ID with
# hardened runtime + secure timestamp.
#
# We resolve the symlink at /opt/homebrew/bin/redis-server to the real
# Mach-O — Homebrew's bin/ entry is a symlink into Cellar/. Bundling
# the real file means the .app stays self-contained even if the
# operator later removes Homebrew.
brew_redis="/opt/homebrew/bin/redis-server"
if [[ ! -e "${brew_redis}" ]]; then
    echo "ERROR: ${brew_redis} not found." >&2
    echo "       Install via: brew install redis" >&2
    exit 2
fi
real_redis="$(/usr/bin/readlink -f "${brew_redis}" 2>/dev/null || /usr/bin/python3 -c "import os; print(os.path.realpath('${brew_redis}'))")"
echo "    source: ${real_redis}"
cp "${real_redis}" "${app_path}/Contents/MacOS/redis-server"
chmod +x "${app_path}/Contents/MacOS/redis-server"
# Verify it is the right architecture for the bundle (arm64).
if ! /usr/bin/file "${app_path}/Contents/MacOS/redis-server" | grep -q "arm64"; then
    echo "ERROR: bundled redis-server is not arm64; the bundle ships only arm64." >&2
    /usr/bin/file "${app_path}/Contents/MacOS/redis-server" >&2
    exit 2
fi

echo "==> bundling LaunchAgent template into Contents/Library/LaunchAgents/"
mkdir -p "${app_path}/Contents/Library/LaunchAgents"
cp "${bundle_dir}/launchagent.plist.template" \
    "${app_path}/Contents/Library/LaunchAgents/me.lopes.openclaw.bridge.plist"
plutil -lint "${app_path}/Contents/Library/LaunchAgents/me.lopes.openclaw.bridge.plist"

if [[ "${skip_sign}" == "1" ]]; then
    echo
    echo "==> SKIP_SIGN=1: stopping after PyInstaller. Bundle layout:"
    echo "    ${app_path}"
    echo "    Verify with: bundle/bridge/test_bundle.sh ${app_path}"
    exit 0
fi

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

# Pass 2: re-sign the helper Mach-Os in MacOS/ with explicit --identifier
# values that nest under the .app's CFBundleIdentifier. Without this,
# codesign auto-derives the identifier from the file basename
# (e.g. "openclaw-register", "redis-server"), which causes
# SMAppService.register() to fail with the unhelpful
# `Foundation._GenericObjCError 0` because the calling binary's
# identifier is unrelated to the bundle it's trying to register a
# LaunchAgent for. Explicit nested identifiers (parent.child format)
# satisfy SMAppService's trust check and stay within the same
# Developer ID team.
echo "==> re-signing helper binaries with nested bundle identifiers"
# IMPORTANT: pass --entitlements on this re-sign too. Without it, the
# helper's entitlements (applied by Pass 1's --deep) are STRIPPED and
# the binary loses `cs.disable-library-validation`. That breakage is
# silent until runtime: redis-server then fails to dlopen Homebrew's
# libssl.3.dylib because dyld with hardened runtime + no
# disable-library-validation rejects cross-Team-ID dylibs ("mapping
# process and mapped file have different Team IDs"). Result: redis
# crashes at startup, supervisor's poison-pill detector exits non-zero,
# bridge never comes up.
for helper_path in \
    "${app_path}/Contents/MacOS/openclaw-register" \
    "${app_path}/Contents/MacOS/redis-server"
do
    helper_name="$(basename "${helper_path}")"
    codesign \
        --force \
        --options runtime \
        --timestamp \
        --identifier "me.lopes.openclaw.bridge.${helper_name}" \
        --entitlements "${bundle_dir}/entitlements.plist" \
        --sign "${DEV_ID_IDENTITY}" \
        "${helper_path}"
done

# Pass 3: re-sign the outer bundle so its CodeResources reflects the
# helpers' new identifiers. This is a non-deep sign — only the bundle
# itself, not nested Mach-Os, gets a fresh signature.
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

if [[ "${skip_notarize}" == "1" ]]; then
    echo
    echo "==> SKIP_NOTARIZE=1: stopping after sign. The bundle is signed but"
    echo "    not notarized — Gatekeeper will reject it for distribution."
    echo "    For a local/dev verification, run:"
    echo "      SKIP_SIGN_CHECKS=1 bundle/bridge/test_bundle.sh"
    echo "    (Standard test_bundle.sh requires the spctl + stapler checks"
    echo "    that only pass on a notarized bundle.)"
    echo
    echo "    Bundle: ${app_path}"
    exit 0
fi

# ---- notarize --------------------------------------------------------

echo "==> zipping for notarization"
zip_path="${bundle_dir}/dist/OpenClawBridge.zip"
rm -f "${zip_path}"
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
echo "    next step: bundle/bridge/test_bundle.sh"
