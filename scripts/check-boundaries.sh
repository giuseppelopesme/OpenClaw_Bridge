#!/usr/bin/env bash
# Enforce the package-boundary rules from docs/repo-layout.md:
#   - relays/* must NOT import from bridge or brains
#   - brains/{name}/* (i.e. anything outside brains/shared) must NOT import from bridge or relays
#   - brains/shared must NOT import from bridge or relays
#   - bridge must NOT import from relays or brains
#
# Allowed cross-package imports: brains/{name} -> brains_shared
#
# Exit non-zero on the first violation. Run from the repo root.

set -euo pipefail

red() { printf '\033[31m%s\033[0m\n' "$*" >&2; }

violations=0

# Helper — fail if `grep` finds an import line. We allow `from __future__`
# and noqa comments by relying on grep's match being on the import line itself.
check() {
    local where="$1"
    local pattern="$2"
    local label="$3"
    if [[ ! -d "$where" ]]; then
        return
    fi
    if grep -RnE --include='*.py' "$pattern" "$where" >&2; then
        red "Boundary violation: $label"
        violations=1
    fi
}

# 1. relays/* must not touch bridge or brains
check "relays" '^[[:space:]]*(from|import)[[:space:]]+bridge(\.|[[:space:]])' \
      "relays/* importing from bridge"
check "relays" '^[[:space:]]*(from|import)[[:space:]]+brains(\.|[[:space:]])' \
      "relays/* importing from brains"
check "relays" '^[[:space:]]*(from|import)[[:space:]]+brains_shared(\.|[[:space:]])' \
      "relays/* importing brains_shared"

# 2. brains/* must not touch bridge or relays
check "brains" '^[[:space:]]*(from|import)[[:space:]]+bridge(\.|[[:space:]])' \
      "brains/* importing from bridge"
check "brains" '^[[:space:]]*(from|import)[[:space:]]+relay(\.|[[:space:]])' \
      "brains/* importing from relay"

# 3. bridge must not touch relays or brains
check "bridge" '^[[:space:]]*(from|import)[[:space:]]+relay(\.|[[:space:]])' \
      "bridge/* importing from relay"
check "bridge" '^[[:space:]]*(from|import)[[:space:]]+brains(\.|[[:space:]])' \
      "bridge/* importing from brains"
check "bridge" '^[[:space:]]*(from|import)[[:space:]]+brains_shared(\.|[[:space:]])' \
      "bridge/* importing brains_shared"

if (( violations )); then
    red "Boundary check failed."
    exit 1
fi
echo "Package boundaries OK."
