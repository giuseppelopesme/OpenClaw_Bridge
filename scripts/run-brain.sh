#!/usr/bin/env bash
# Run the brain process in production mode.
#
# Mirrors scripts/run-bridge.sh: sets PYTHONPATH explicitly to side-step
# the uv 0.11.x hidden-`.pth` issue, then execs `python -m agent`.
#
# BRAIN_TOKEN is loaded from macOS Keychain (actor `brain.<agent>`, the
# same entry scripts/mint-token.py writes), avoiding plaintext-in-plist.
# If BRAIN_TOKEN is already set in the environment it wins (useful for
# tests/dev); otherwise the Keychain copy is used.
#
# AGENT_NAME selects which brain identity to run as. Defaults to
# "agent" — matches the brain package's DEFAULT_AGENT_NAME and the
# Keychain actor key the supervisor / installer plant.
#
# Optional env (see brains/agent/src/agent/config.py):
#   - BRIDGE_URL    (default http://127.0.0.1:8788)
#   - AGENT_NAME    (default "agent")
#   - STATE_DB_PATH (default ~/.openclaw/<agent>.state.db)

set -euo pipefail

cd "$(dirname "$0")/.."
repo_root="$(pwd)"

agent_name="${AGENT_NAME:-agent}"
export AGENT_NAME="${agent_name}"

if [[ -z "${BRAIN_TOKEN:-}" ]]; then
    BRAIN_TOKEN="$(
        PYTHONPATH="${repo_root}/bridge/src" \
        AGENT_NAME="${agent_name}" \
        uv run --no-sync python - <<'PY'
import os
import sys
from bridge import keychain

actor = f"brain.{os.environ['AGENT_NAME']}"
cred = keychain.get_credential(actor)
if cred is None or not cred.token:
    sys.stderr.write(
        f"ERROR: no Keychain credential for {actor}. Mint one with:\n"
        f"    scripts/mint-token.py --actor {actor} --scopes "
        "llm:call,vault:read,vault:write,events:subscribe,events:publish,"
        "agent:drafts:write\n",
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
    "$repo_root/brains/agent/src"
    "$repo_root/brains/shared/src"
)
joined="$(IFS=:; echo "${src_dirs[*]}")"
export PYTHONPATH="${joined}${PYTHONPATH:+:$PYTHONPATH}"

exec uv run --no-sync python -m agent "$@"
