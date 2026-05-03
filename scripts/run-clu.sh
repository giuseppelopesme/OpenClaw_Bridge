#!/usr/bin/env bash
# Run the CLU brain in production mode.
#
# Mirrors scripts/run-bridge.sh and scripts/run-relay.sh: sets PYTHONPATH
# explicitly to side-step the uv 0.11.x hidden-`.pth` issue, then execs
# `python -m clu`.
#
# Required env (see brains/clu/src/clu/config.py):
#   - BRAIN_TOKEN — bearer minted via scripts/mint-token.py with scopes
#       llm:call, vault:read, vault:write,
#       events:subscribe, events:publish, imessage:send
# Optional env:
#   - BRIDGE_URL    (default http://127.0.0.1:8788)
#   - STATE_DB_PATH (default ~/.openclaw/clu.state.db)

set -euo pipefail

cd "$(dirname "$0")/.."
repo_root="$(pwd)"

src_dirs=(
    "$repo_root/brains/clu/src"
    "$repo_root/brains/shared/src"
)
joined="$(IFS=:; echo "${src_dirs[*]}")"
export PYTHONPATH="${joined}${PYTHONPATH:+:$PYTHONPATH}"

exec uv run --no-sync python -m clu "$@"
