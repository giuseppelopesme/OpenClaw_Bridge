#!/usr/bin/env bash
# Run Redis with the OpenClaw config and the requirepass loaded from Keychain.
#
# Usage:
#     ./scripts/run-redis.sh                # foreground; Ctrl-C to stop
#
# The Keychain item is service `com.giuseppelopesme.openclaw.bridge`,
# account `provider.redis`, password = JSON `{"token": "<secret>", ...}`
# (same shape every other actor/provider uses; see bridge/keychain.py).
#
# To bootstrap the password on a fresh host (one-off):
#
#     uv run --no-sync python -c '
#     import secrets
#     from bridge import keychain
#     keychain.set_credential("provider.redis", secrets.token_hex(32), [])
#     '
#
# We pass the password to redis-server as a command-line arg
# (--requirepass <secret>). On macOS the argv of a process is visible to
# the same user only, so the secret stays inside the user account.

set -euo pipefail

cd "$(dirname "$0")/.."
repo_root="$(pwd)"
conf="${repo_root}/ops/redis/redis.conf"
src="${repo_root}/bridge/src"

if [[ ! -f "$conf" ]]; then
    printf 'redis.conf not found at %s\n' "$conf" >&2
    exit 1
fi

# Pull the password out of Keychain via the same wrapper the bridge uses.
# We run a tiny Python snippet so we don't have to know the JSON shape.
password="$(
    PYTHONPATH="${src}" \
    uv run --no-sync python - <<'PY'
import sys
from bridge import keychain
cred = keychain.get_credential("provider.redis")
if cred is None or not cred.token:
    sys.stderr.write(
        "ERROR: no Keychain credential for provider.redis. "
        "See scripts/run-redis.sh for the bootstrap command.\n"
    )
    sys.exit(1)
sys.stdout.write(cred.token)
PY
)"

if [[ -z "${password}" ]]; then
    exit 1
fi

exec redis-server "${conf}" --requirepass "${password}"
