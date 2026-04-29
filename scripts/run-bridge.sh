#!/usr/bin/env bash
# Run the bridge in production mode with structured JSON logging.
#
# Workaround for uv 0.11.x + Python 3.13: uv flags editable `.pth` files as
# macOS hidden, which `site.py` skips. We side-step by setting PYTHONPATH
# directly; remove this once a fixed uv lands.

set -euo pipefail

cd "$(dirname "$0")/.."

repo_root="$(pwd)"
src_dirs=(
    "$repo_root/bridge/src"
    "$repo_root/brains/shared/src"
    "$repo_root/brains/clu/src"
    "$repo_root/relays/imessage/src"
)

joined="$(IFS=:; echo "${src_dirs[*]}")"
export PYTHONPATH="${joined}${PYTHONPATH:+:$PYTHONPATH}"

exec uv run --no-sync python -m bridge "$@"
