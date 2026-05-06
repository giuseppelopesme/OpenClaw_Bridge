#!/usr/bin/env bash
# Build, sign, notarize, and staple MacOSBridgeForOpenClaw.pkg.
#
# Composition: a "distribution" pkg wrapping two component packages
# (OpenClawBridge.app and OpenClawRelay.app) plus a postinstall script
# (installer/scripts/postinstall) that drops the LaunchAgents and asks
# the operator which user account runs the iMessage relay.
#
# Usage:
#     installer/build-pkg.sh                       # full build
#     SKIP_SIGN=1 installer/build-pkg.sh           # productbuild only
#     SKIP_NOTARIZE=1 installer/build-pkg.sh       # sign but do not notarize
#
# Required env (when not SKIP_SIGN=1):
#
#     TEAM_ID                       Apple Developer team identifier.
#     DEV_ID_INSTALLER_IDENTITY     Full "Developer ID Installer: ..." string.
#                                   Distinct from the Application identity used
#                                   by bundle/{bridge,relay}/build.sh.
#
# Required env (only when not SKIP_NOTARIZE=1):
#
#     NOTARY_PROFILE                notarytool keychain profile
#                                   (e.g. MacOs-OpenClaw.Notary).
#
# Prerequisites that this script does NOT build for you (run them first):
#
#     bundle/bridge/build.sh        produces bundle/bridge/dist/OpenClawBridge.app
#     bundle/relay/build.sh         produces bundle/relay/dist/OpenClawRelay.app
#
# Both .app bundles must be Developer-ID-Application signed at minimum;
# notarization of the inner .app bundles is not strictly required for the
# pkg itself to notarize, but is recommended (Apple validates the inner
# signatures during pkg notarization regardless).
#
# Idempotent: re-running cleans dist/ and rebuilds. The notarization
# request is fresh each time.

set -euo pipefail

# ---- locate ourselves ------------------------------------------------

installer_dir="$(cd "$(dirname "$0")" && pwd)"
repo_root="$(cd "${installer_dir}/.." && pwd)"

# ---- preflight -------------------------------------------------------

skip_sign="${SKIP_SIGN:-0}"
skip_notarize="${SKIP_NOTARIZE:-0}"

bridge_app="${repo_root}/bundle/bridge/dist/OpenClawBridge.app"
relay_app="${repo_root}/bundle/relay/dist/OpenClawRelay.app"
[[ -d "${bridge_app}" ]] || {
    echo "ERROR: ${bridge_app} not found." >&2
    echo "       Build it first: bundle/bridge/build.sh" >&2
    exit 2
}
[[ -d "${relay_app}" ]] || {
    echo "ERROR: ${relay_app} not found." >&2
    echo "       Build it first: bundle/relay/build.sh" >&2
    exit 2
}

if [[ "${skip_sign}" != "1" ]]; then
    : "${TEAM_ID:?TEAM_ID env var required}"
    : "${DEV_ID_INSTALLER_IDENTITY:?DEV_ID_INSTALLER_IDENTITY env var required (full \"Developer ID Installer: ...\" string)}"

    if ! security find-identity -v | grep -q -F "${DEV_ID_INSTALLER_IDENTITY}"; then
        echo "ERROR: '${DEV_ID_INSTALLER_IDENTITY}' not found in login keychain." >&2
        echo "       Obtain a Developer ID Installer cert from developer.apple.com →" >&2
        echo "       Account → Certificates, Identifiers & Profiles → Certificates → +." >&2
        echo "       Verify with: security find-identity -v" >&2
        exit 2
    fi

    if [[ "${skip_notarize}" != "1" ]]; then
        : "${NOTARY_PROFILE:?NOTARY_PROFILE env var required (e.g. MacOs-OpenClaw.Notary)}"
        if ! xcrun notarytool history --keychain-profile "${NOTARY_PROFILE}" >/dev/null 2>&1; then
            echo "ERROR: notarytool profile '${NOTARY_PROFILE}' is not authenticated." >&2
            echo "       Or pass SKIP_NOTARIZE=1 to sign without notarizing." >&2
            exit 2
        fi
    fi
fi

# ---- versions -------------------------------------------------------

read_version() {
    awk -F '"' '/^version *= *"/ { print $2; exit }' "$1"
}

bridge_version="$(read_version "${repo_root}/bridge/pyproject.toml")"
relay_version="$(read_version "${repo_root}/relays/imessage/pyproject.toml")"
[[ -n "${bridge_version}" ]] || { echo "ERROR: cannot read bridge version" >&2; exit 2; }
[[ -n "${relay_version}"  ]] || { echo "ERROR: cannot read relay version"  >&2; exit 2; }

# Use the bridge version for the outer pkg — it's the headline component.
pkg_version="${bridge_version}"
echo "==> building MacOSBridgeForOpenClaw.pkg v${pkg_version}"
echo "    bridge.app v${bridge_version}, relay.app v${relay_version}"

# ---- clean ----------------------------------------------------------

dist_dir="${installer_dir}/dist"
build_dir="${installer_dir}/build"
rm -rf "${dist_dir}" "${build_dir}"
mkdir -p "${dist_dir}" "${build_dir}"

# ---- component pkgs --------------------------------------------------

# Use `--root` mode (not `--component`) so pkgbuild treats each .app as
# a directory tree to install verbatim, with no bundle-relocation rule.
#
# The `--component` mode applies a default `BundleIsRelocatable=true`
# behavior: at install time PackageKit searches the target volume for
# any existing copy of the bundle (matched by CFBundleIdentifier) and
# "installs" by overwriting that path INSTEAD OF the configured
# --install-location. On a developer machine this finds the .app at
# `bundle/<x>/dist/...` (the very source we're packaging) and silently
# relocates the install away from /Applications, leaving nothing where
# the postinstall expects it. `--root` avoids the entire mechanism.
#
# Stage each .app into a directory whose contents mirror the install
# layout under /Applications, then point pkgbuild at the staging dir.

stage_app() {
    # $1: source .app path
    # $2: staging dir (must not exist yet)
    local src="$1" stage="$2"
    mkdir -p "${stage}"
    cp -R "${src}" "${stage}/"
}

# pkgbuild auto-generates a component plist with BundleIsRelocatable=true
# even in --root mode; we then explicitly flip it false. Without this,
# PackageKit at install time finds the source .app under bundle/<x>/dist/
# and "installs" by overwriting that path INSTEAD of /Applications,
# leaving nothing where the postinstall expects to look.
#
# `scripts_dir` is optional — when set, pkgbuild embeds it inside the
# component as `Scripts/`. Apple Installer only runs scripts at the
# COMPONENT level; scripts placed at the distribution (productbuild's
# --scripts) are dead weight and never execute. Our postinstall lives
# in the bridge component since both components always ship together.
build_component_pkg() {
    # $1: stage dir
    # $2: identifier
    # $3: version
    # $4: output pkg path
    # $5: optional scripts dir (empty = no scripts)
    local stage="$1" ident="$2" ver="$3" out="$4" scripts_dir="${5:-}"
    local plist="${stage}.component.plist"

    pkgbuild --analyze --root "${stage}" "${plist}"

    # Flip BundleIsRelocatable=false on every entry. PlistBuddy doesn't
    # iterate well, but the output of `--analyze` for these single-bundle
    # roots is a one-element array, so addressing index 0 is safe.
    /usr/libexec/PlistBuddy \
        -c "Set :0:BundleIsRelocatable false" \
        "${plist}"

    local extra_args=()
    if [[ -n "${scripts_dir}" ]]; then
        extra_args+=(--scripts "${scripts_dir}")
    fi

    # `${extra_args[@]+...}` expands only when the array is set, so we
    # do not trip `set -u` (nounset) on an empty array under macOS bash 3.2.
    pkgbuild \
        --root "${stage}" \
        --component-plist "${plist}" \
        --install-location "/Applications" \
        --identifier "${ident}" \
        --version "${ver}" \
        ${extra_args[@]+"${extra_args[@]}"} \
        "${out}"
}

bridge_stage="${build_dir}/stage-bridge"
relay_stage="${build_dir}/stage-relay"
stage_app "${bridge_app}" "${bridge_stage}"
stage_app "${relay_app}"  "${relay_stage}"

echo "==> pkgbuild OpenClawBridge.pkg (with embedded postinstall)"
build_component_pkg \
    "${bridge_stage}" \
    "me.lopes.openclaw.bridge.pkg" \
    "${bridge_version}" \
    "${build_dir}/OpenClawBridge.pkg" \
    "${installer_dir}/scripts"

echo "==> pkgbuild OpenClawRelay.pkg"
build_component_pkg \
    "${relay_stage}" \
    "me.lopes.openclaw.relay.pkg" \
    "${relay_version}" \
    "${build_dir}/OpenClawRelay.pkg"

# ---- distribution pkg -----------------------------------------------

echo "==> productbuild MacOSBridgeForOpenClaw.pkg (unsigned)"

# Substitute version placeholders into Distribution.xml.
distribution="${build_dir}/Distribution.xml"
sed \
    -e "s|__BRIDGE_VERSION__|${bridge_version}|g" \
    -e "s|__RELAY_VERSION__|${relay_version}|g" \
    "${installer_dir}/Distribution.xml" \
    > "${distribution}"

unsigned_pkg="${build_dir}/MacOSBridgeForOpenClaw-unsigned.pkg"
# Note: NO --scripts flag here. Distribution-level scripts are not run
# by Apple Installer; the postinstall is embedded inside the bridge
# component pkg via the build_component_pkg call above.
#
# --resources points productbuild at the directory holding welcome.html
# and conclusion.html (referenced from Distribution.xml). Without this
# flag the panes silently render as empty pages.
productbuild \
    --distribution "${distribution}" \
    --package-path "${build_dir}" \
    --resources "${installer_dir}/resources" \
    --version "${pkg_version}" \
    "${unsigned_pkg}"

if [[ "${skip_sign}" == "1" ]]; then
    final_pkg="${dist_dir}/MacOSBridgeForOpenClaw.pkg"
    cp "${unsigned_pkg}" "${final_pkg}"
    echo
    echo "==> SKIP_SIGN=1: stopping after productbuild."
    echo "    ${final_pkg}"
    echo "    Verify with: pkgutil --check-signature \"${final_pkg}\" (will report 'unsigned')."
    echo "    Or expand:   pkgutil --expand \"${final_pkg}\" /tmp/openclaw-pkg-expand"
    exit 0
fi

# ---- productsign ----------------------------------------------------

echo "==> productsign with Developer ID Installer"
signed_pkg="${dist_dir}/MacOSBridgeForOpenClaw.pkg"
productsign \
    --sign "${DEV_ID_INSTALLER_IDENTITY}" \
    "${unsigned_pkg}" \
    "${signed_pkg}"

echo "==> verifying signature"
pkgutil --check-signature "${signed_pkg}"

if [[ "${skip_notarize}" == "1" ]]; then
    echo
    echo "==> SKIP_NOTARIZE=1: stopping after sign. Pkg is signed but not"
    echo "    notarized — Gatekeeper will warn the user on first install."
    echo "    ${signed_pkg}"
    exit 0
fi

# ---- notarize -------------------------------------------------------

echo "==> submitting pkg to notarytool (this typically takes 1–3 minutes)"
xcrun notarytool submit \
    "${signed_pkg}" \
    --keychain-profile "${NOTARY_PROFILE}" \
    --wait

echo "==> stapling notarization ticket"
xcrun stapler staple "${signed_pkg}"
xcrun stapler validate "${signed_pkg}"

echo
echo "==> SUCCESS: ${signed_pkg}"
echo "    Test with: open \"${signed_pkg}\""
