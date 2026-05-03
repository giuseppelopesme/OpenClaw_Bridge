#!/usr/bin/env bash
# Fail the commit if the checked-in docs/openapi-v1.yaml does not match
# what `tools/dump-openapi.py` would render right now.
#
# Run via the pre-commit hook (see .pre-commit-config.yaml). Manual
# regeneration: `tools/regen-sdk.sh` (which both refreshes the YAML and
# re-runs the SDK generator).

set -euo pipefail

cd "$(dirname "$0")/.."

target="docs/openapi-v1.yaml"
actual_sha="$(uv run --no-sync python tools/dump-openapi.py >/dev/null && shasum "$target" | awk '{print $1}')"

# `dump-openapi.py` already wrote the fresh YAML to the target. If git
# now sees the file as modified, it has drifted from the committed copy.
if ! git diff --quiet -- "$target"; then
    echo "ERROR: $target is out of sync with the bridge code." >&2
    echo "       Run: tools/regen-sdk.sh" >&2
    echo "       Then commit both $target and brains/shared/src/brains_shared/_generated/." >&2
    git diff --stat -- "$target" >&2
    exit 1
fi

# Sanity check — print the hash so CI logs show the YAML version.
echo "OK: $target ($actual_sha)"
