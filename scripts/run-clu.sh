#!/usr/bin/env bash
# Run the CLU brain in production mode.
#
# Mirrors scripts/run-bridge.sh and scripts/run-relay.sh: sets PYTHONPATH
# explicitly to side-step the uv 0.11.x hidden-`.pth` issue, then execs
# `python -m clu`.
#
# BRAIN_TOKEN is loaded from macOS Keychain (actor `brain.clu`, the same
# entry scripts/mint-token.py writes), avoiding plaintext-in-plist. If
# BRAIN_TOKEN is already set in the environment it wins (useful for
# tests/dev); otherwise the Keychain copy is used.
#
# Optional env (see brains/clu/src/clu/config.py):
#   - BRIDGE_URL    (default http://127.0.0.1:8788)
#   - STATE_DB_PATH (default ~/.openclaw/clu.state.db)

set -euo pipefail

cd "$(dirname "$0")/.."
repo_root="$(pwd)"

if [[ -z "${BRAIN_TOKEN:-}" ]]; then
    BRAIN_TOKEN="$(
        PYTHONPATH="${repo_root}/bridge/src" \
        uv run --no-sync python - <<'PY'
import sys
from bridge import keychain
cred = keychain.get_credential("brain.clu")
if cred is None or not cred.token:
    sys.stderr.write(
        "ERROR: no Keychain credential for brain.clu. Mint one with:\n"
        "    scripts/mint-token.py --actor brain.clu --scopes "
        "llm:call,vault:read,vault:write,events:subscribe,events:publish,"
        "agent:drafts:write\n"
    )
    sys.exit(1)
sys.stdout.write(cred.token)
PY
    )"
    if [[ -z "${BRAIN_TOKEN}" ]]; then
        exit 1
    fi
    export BRAIN_TOKEN
fi

src_dirs=(
    "$repo_root/brains/clu/src"
    "$repo_root/brains/shared/src"
)
joined="$(IFS=:; echo "${src_dirs[*]}")"
export PYTHONPATH="${joined}${PYTHONPATH:+:$PYTHONPATH}"

exec uv run --no-sync python -m clu "$@"
