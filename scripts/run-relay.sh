#!/usr/bin/env bash
# Run an iMessage relay process in production mode.
#
# Usage:  scripts/run-relay.sh <agent>
#
# `<agent>` must be one of `clu | tron | flynn`. Sets AGENT_NAME from the
# argument so the relay's RelayConfig.from_env picks it up.
#
# RELAY_TOKEN (the bridge bearer) is loaded from macOS Keychain under
# actor `relay.<agent>` — same entry scripts/mint-token.py writes from
# the bridge host. Because the relay runs as a separate macOS user
# (e.g. `clu`) with its own login keychain, the operator must store the
# plaintext in that user's keychain after minting on the bridge host
# (or run mint-token.py from this user account, which stores into the
# local keychain). See ops/launchd/com.giuseppelopesme.openclaw.relay.<agent>.plist
# for the full setup flow. RELAY_TOKEN in the environment takes
# precedence (useful for tests/dev).
#
# Workaround for uv 0.11.x + Python 3.13: uv flags editable `.pth` files
# as macOS hidden, which `site.py` skips. PYTHONPATH is set explicitly;
# remove this once a fixed uv lands.

set -euo pipefail

if [[ $# -lt 1 ]]; then
    echo "usage: $0 <agent>  (clu|tron|flynn)" >&2
    exit 2
fi

agent="$1"
shift

cd "$(dirname "$0")/.."
repo_root="$(pwd)"

if [[ -z "${RELAY_TOKEN:-}" ]]; then
    RELAY_TOKEN="$(
        PYTHONPATH="${repo_root}/bridge/src" \
        AGENT="${agent}" \
        uv run --no-sync python - <<'PY'
import os
import sys
from bridge import keychain
actor = f"relay.{os.environ['AGENT']}"
cred = keychain.get_credential(actor)
if cred is None or not cred.token:
    sys.stderr.write(
        f"ERROR: no Keychain credential for {actor!r} in this user's "
        f"keychain. On the bridge host (giuseppelopes) run:\n"
        f"    scripts/mint-token.py --actor {actor} --scopes imessage:relay\n"
        f"Then store the same plaintext in this user's login keychain "
        f"(Keychain Access -> New, service "
        f"`com.giuseppelopesme.openclaw.bridge`, account "
        f"`{actor}`), or rerun mint-token.py from this user account.\n"
    )
    sys.exit(1)
sys.stdout.write(cred.token)
PY
    )"
    if [[ -z "${RELAY_TOKEN}" ]]; then
        exit 1
    fi
    export RELAY_TOKEN
fi

src_dirs=(
    "$repo_root/relays/imessage/src"
)
joined="$(IFS=:; echo "${src_dirs[*]}")"
export PYTHONPATH="${joined}${PYTHONPATH:+:$PYTHONPATH}"

export AGENT_NAME="$agent"

exec uv run --no-sync python -m relay.main "$@"
