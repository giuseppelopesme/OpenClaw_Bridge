#!/usr/bin/env bash
# One-shot Keychain namespace migration.
#
# Copies generic-password items from
#     com.giuseppelopesme.openclaw.bridge   (old)
# to
#     me.lopes.openclaw.bridge              (new)
#
# Run once per user whose login keychain holds entries:
#
#     # As the main user — migrates the bridge manifest and every actor
#     # it lists (cli.*, brain.*, relay.*, provider.*).
#     bash scripts/migrate-keychain-namespace.sh
#
#     # As the relay's service-user account — migrates just the relay
#     # token slot.
#     bash scripts/migrate-keychain-namespace.sh relay.<account>
#
#     # Read from a specific keychain (e.g. an OS-renamed one):
#     bash scripts/migrate-keychain-namespace.sh \
#         --from ~/Library/Keychains/login_renamed_1.keychain-db
#
# Discovery: if the bridge's _actors_ manifest item exists under the old
# service, every account it names is migrated automatically. Any extra
# account names passed as arguments are also migrated. The relay's
# service-user keychain has no manifest (it's touched directly by
# setup-relay-account.sh, not by the bridge module), so explicit args
# are the only path there.
#
# Source keychain selection: by default, reads use the user's active
# search list. Pass --from <path> to read from a specific keychain
# (e.g. login_renamed_1.keychain-db, which macOS creates when it
# rotates the login keychain after a major OS upgrade and which is
# NOT in the search list anymore). Writes always go to the default
# keychain (so the bridge sees them at runtime).
#
# Safety: the script COPIES, never deletes. Old entries stay in place
# until you verify the new ones load and run the cleanup commands the
# script prints at the end.
#
# Idempotent: re-running just rewrites the same payloads.

set -euo pipefail

OLD_SVC="com.giuseppelopesme.openclaw.bridge"
NEW_SVC="me.lopes.openclaw.bridge"
SECURITY="/usr/bin/security"
SOURCE_KEYCHAIN=""

# Parse leading --from <path> if present, then drop it from the arg list.
if [[ "${1:-}" == "--from" ]]; then
    if [[ $# -lt 2 ]]; then
        echo "ERROR: --from requires a keychain path argument" >&2
        exit 2
    fi
    SOURCE_KEYCHAIN="$2"
    shift 2
    if [[ ! -f "${SOURCE_KEYCHAIN}" ]]; then
        echo "ERROR: source keychain not found: ${SOURCE_KEYCHAIN}" >&2
        exit 2
    fi
fi

if [[ ! -x "${SECURITY}" ]]; then
    echo "ERROR: ${SECURITY} not found — running on a non-macOS host?" >&2
    exit 2
fi

# Read from OLD_SVC. If --from was given, the read is scoped to that
# keychain; otherwise it walks the user's search list. The trailing
# positional arg of `find-generic-password` is the keychain path —
# we omit it (empty) to use the search list.
read_old() {
    local account="$1"
    if [[ -n "${SOURCE_KEYCHAIN}" ]]; then
        "${SECURITY}" find-generic-password \
            -s "${OLD_SVC}" -a "${account}" -w "${SOURCE_KEYCHAIN}"
    else
        "${SECURITY}" find-generic-password \
            -s "${OLD_SVC}" -a "${account}" -w
    fi
}

copy_one() {
    local account="$1"
    local payload
    if ! payload=$(read_old "${account}" 2>/dev/null); then
        echo "  skip: ${account} (not in source)"
        return 1
    fi
    "${SECURITY}" add-generic-password \
        -U \
        -s "${NEW_SVC}" \
        -a "${account}" \
        -w "${payload}" \
        >/dev/null
    echo "  copied: ${account}"
    return 0
}

# Collect accounts: explicit args + manifest discovery.
declare -a accounts=("$@")

if manifest=$(read_old "_actors_" 2>/dev/null); then
    echo "==> discovered _actors_ manifest under ${OLD_SVC}"
    # Parse the JSON list with stdlib python3. Apple ships /usr/bin/python3
    # since Big Sur via the Command Line Tools; no extra deps needed.
    while IFS= read -r actor; do
        [[ -n "${actor}" ]] || continue
        accounts+=("${actor}")
    done < <(printf '%s' "${manifest}" | /usr/bin/python3 -c '
import json, sys
try:
    items = json.load(sys.stdin)
except Exception:
    sys.exit(0)
if isinstance(items, list):
    for a in items:
        if isinstance(a, str):
            print(a)
')
    accounts+=("_actors_")
fi

# Deduplicate while preserving order (keeps explicit args first in output).
# Avoid `declare -A` so we run on macOS's bash 3.2 without depending on brew.
declare -a uniq=()
for a in "${accounts[@]}"; do
    found=0
    for b in "${uniq[@]:-}"; do
        [[ "${a}" == "${b}" ]] && { found=1; break; }
    done
    [[ "${found}" -eq 0 ]] && uniq+=("${a}")
done

if [[ ${#uniq[@]} -eq 0 ]]; then
    echo "ERROR: nothing to migrate." >&2
    echo "       Either no _actors_ manifest in ${OLD_SVC}, and no account" >&2
    echo "       names were passed as arguments. Try:" >&2
    echo "         bash $0 relay.<account>     # for a relay service-user account" >&2
    exit 2
fi

echo "==> migrating ${#uniq[@]} account(s) from ${OLD_SVC} to ${NEW_SVC}"
copied=0
for account in "${uniq[@]}"; do
    if copy_one "${account}"; then
        copied=$((copied + 1))
    fi
done

echo
echo "==> migrated ${copied} of ${#uniq[@]} accounts"

# Verify each new entry is readable.
echo
echo "==> verifying new namespace"
verify_failed=0
for account in "${uniq[@]}"; do
    if "${SECURITY}" find-generic-password \
            -s "${NEW_SVC}" -a "${account}" -w >/dev/null 2>&1; then
        echo "  ok: ${account}"
    else
        echo "  MISSING: ${account}"
        verify_failed=$((verify_failed + 1))
    fi
done

if [[ ${verify_failed} -gt 0 && ${copied} -gt 0 ]]; then
    echo
    echo "WARNING: ${verify_failed} account(s) failed verification." >&2
    echo "         Inspect with: security dump-keychain | grep -A4 ${NEW_SVC}" >&2
fi

echo
echo "==> next steps"
echo
echo "1. Start the bridge / relay against the new namespace and confirm"
echo "   they load tokens cleanly (logs should show no Keychain errors)."
echo
echo "2. Once verified, delete the old entries one at a time:"
for account in "${uniq[@]}"; do
    echo "     security delete-generic-password -s '${OLD_SVC}' -a '${account}'"
done
