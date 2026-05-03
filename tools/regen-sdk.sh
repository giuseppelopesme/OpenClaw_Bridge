#!/usr/bin/env bash
# Regenerate the brains_shared SDK from the live bridge code.
#
# Steps:
#   1. Re-render docs/openapi-v1.yaml from bridge.main:app.openapi().
#   2. Re-run openapi-python-client into brains/shared/src/brains_shared/_generated/.
#   3. Strip the generator's transient .ruff_cache so it doesn't end up
#      in git.
#
# After running, commit both docs/openapi-v1.yaml and the regenerated
# _generated/ tree together. The hand-written wrappers in
# brains/shared/src/brains_shared/{client,eventbus,obsidian,llm}.py do
# not change automatically — verify they still typecheck and pass tests
# before merging.

set -euo pipefail

cd "$(dirname "$0")/.."
repo_root="$(pwd)"

echo "→ Dumping OpenAPI to docs/openapi-v1.yaml"
uv run --no-sync python tools/dump-openapi.py

echo "→ Re-generating brains_shared/_generated/"
out_dir="$repo_root/brains/shared/src/brains_shared/_generated"
rm -rf "$out_dir"
mkdir -p "$out_dir"
uv run --no-sync openapi-python-client generate \
    --path docs/openapi-v1.yaml \
    --output-path "$out_dir" \
    --meta none \
    --overwrite >/dev/null
rm -rf "$out_dir/.ruff_cache"

echo "→ Done. Now run: uv run --no-sync mypy && uv run --no-sync pytest -q"
