#!/usr/bin/env bash
# One-shot bootstrap for the clu user account (run AS clu, not giuseppelopes).
#
# Usage:
#     bash scripts/setup-clu-account.sh <relay-token-plaintext>
#
# The plaintext token must already exist in giuseppelopes's Keychain
# under actor `relay.clu` (the bridge validates against that). Mint it
# on the bridge host with:
#     scripts/mint-token.py --actor relay.clu --scopes imessage:relay
#
# This script:
#   1. Stores the plaintext in clu's login keychain so run-relay.sh
#      can read it.
#   2. Clones the OpenClaw_Bridge repo to /Users/clu/Runtime/OpenClaw_Bridge.
#   3. Runs `uv sync --group dev` to build clu's venv.
#   4. Copies the relay.clu launchd plist into ~/Library/LaunchAgents.
#   5. Bootstraps the launchd job in clu's GUI domain.
#
# Idempotent: re-running updates the keychain entry, fast-forwards the
# repo, re-runs uv sync, replaces the plist, and reloads the launchd job.

set -euo pipefail

if [[ "$(id -un)" != "clu" ]]; then
    echo "ERROR: run this AS the clu user, not $(id -un)." >&2
    echo "Try: sudo su - clu" >&2
    exit 2
fi

if [[ $# -lt 1 ]]; then
    echo "usage: $0 <relay-token-plaintext>" >&2
    exit 2
fi

token="$1"
runtime="/Users/clu/Runtime/OpenClaw_Bridge"
repo_url="https://github.com/giuseppelopesme/OpenClaw_Bridge.git"

echo "==> 1. storing relay.clu token in clu's login keychain"
payload="{\"token\":\"${token}\",\"scopes\":[\"imessage:relay\"]}"
# -U replaces any existing item under the same (service, account).
security add-generic-password \
    -U \
    -a relay.clu \
    -s com.giuseppelopesme.openclaw.bridge \
    -w "${payload}"

echo "==> 2. cloning runtime to ${runtime}"
mkdir -p "$(dirname "${runtime}")"
if [[ -d "${runtime}/.git" ]]; then
    git -C "${runtime}" fetch origin
    git -C "${runtime}" checkout main
    git -C "${runtime}" pull --ff-only origin main
else
    git clone "${repo_url}" "${runtime}"
fi

echo "==> 3. uv sync (this may take a minute on first run)"
cd "${runtime}"
uv sync --group dev

echo "==> 4. installing launchd plist"
mkdir -p ~/Library/LaunchAgents
cp "${runtime}/ops/launchd/com.giuseppelopesme.openclaw.relay.clu.plist" \
    ~/Library/LaunchAgents/

echo "==> 5. bootstrapping launchd job"
# Bootout first if already loaded so we get a clean reload.
launchctl bootout gui/$(id -u)/com.giuseppelopesme.openclaw.relay.clu 2>/dev/null || true
launchctl bootstrap gui/$(id -u) \
    ~/Library/LaunchAgents/com.giuseppelopesme.openclaw.relay.clu.plist

sleep 2
echo
echo "==> done. status:"
launchctl list | grep openclaw || true
echo
echo "Tail logs with:"
echo "    tail -f ~/.openclaw/relay.clu.err.log"
echo
echo "Note: first send may prompt 'Terminal/Python wants to control"
echo "Messages.app' — click OK. macOS may also require Full Disk Access"
echo "for the Python binary to read chat.db (System Settings > Privacy"
echo "& Security > Full Disk Access)."
