#!/usr/bin/env bash
# Run an iMessage relay process in production mode.
#
# Usage:  scripts/run-relay.sh <agent>
#
# `<agent>` must be one of `clu | tron | flynn`. Sets AGENT_NAME from the
# argument so the relay's RelayConfig.from_env picks it up. RELAY_TOKEN
# (the bridge bearer) is expected in the environment — see
# ops/launchd/com.giuseppelopesme.openclaw.relay.<agent>.plist for the
# launchd-driven path.
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

src_dirs=(
    "$repo_root/relays/imessage/src"
)
joined="$(IFS=:; echo "${src_dirs[*]}")"
export PYTHONPATH="${joined}${PYTHONPATH:+:$PYTHONPATH}"

export AGENT_NAME="$agent"

exec uv run --no-sync python -m relay.main "$@"
