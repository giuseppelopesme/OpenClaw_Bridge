#!/usr/bin/env bash
# Run the OpenClaw process supervisor — bridge + brain.agent under one parent.
#
# This is the canonical *production* launcher as of Step 1 of the
# Bridge.app re-platform. The supervisor owns:
#
#   1. bridge    — `python -m bridge`     — FastAPI on 127.0.0.1:8788
#   2. brain.agent — `python -m agent`     — agent process
#
# Redis stays external — install via Homebrew and start it separately
# (`brew services start redis`, or scripts/run-redis.sh in dev). The
# supervisor will eventually swallow Redis too once we vendor a binary
# into the .app bundle, but not yet.
#
# For dev/tests:
#   - scripts/run-bridge.sh   — bridge alone, no brain.
#   - scripts/run-brain.sh      — brain alone, against an already-running bridge.
#
# Workaround for uv 0.11.x + Python 3.13: uv flags editable `.pth` files
# as macOS hidden, which `site.py` skips. We side-step by setting
# PYTHONPATH directly; remove this once a fixed uv lands.

set -euo pipefail

cd "$(dirname "$0")/.."

repo_root="$(pwd)"
src_dirs=(
    "$repo_root/bridge/src"
    "$repo_root/brains/shared/src"
    "$repo_root/brains/agent/src"
    "$repo_root/relays/imessage/src"
)

joined="$(IFS=:; echo "${src_dirs[*]}")"
export PYTHONPATH="${joined}${PYTHONPATH:+:$PYTHONPATH}"

exec uv run --no-sync python -m bridge.supervisor "$@"
