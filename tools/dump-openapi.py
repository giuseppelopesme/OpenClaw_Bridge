#!/usr/bin/env python3
"""Render bridge.main:app.openapi() to docs/openapi-v1.yaml.

Idempotent: re-runs produce byte-identical output unless the spec
genuinely changed. The pre-commit hook re-runs this and fails the
commit if the YAML drifts from the code.

### Determinism

FastAPI's `app.openapi()` returns a fresh dict on every call. The dict
itself is dependency-ordered: paths come out in route-registration order,
which is stable across runs as long as `main.create_app` is. We add
two belt-and-braces measures:

1. ``yaml.safe_dump(..., sort_keys=True)`` so every nested object's
   keys are alphabetised — no hidden churn from Pydantic schema-ref
   ordering.
2. Top-level keys are also alphabetised by passing the dict through
   ``json.dumps(..., sort_keys=True) + json.loads`` first. This nukes
   any insertion-order surprises in nested ``$ref`` blocks.

If a future FastAPI/Pydantic upgrade introduces non-determinism, fix
that here — don't paper it over with a `--allow-drift` flag.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parent.parent
SRC_PATHS = [
    REPO_ROOT / "bridge" / "src",
    REPO_ROOT / "brains" / "shared" / "src",
    REPO_ROOT / "brains" / "agent" / "src",
    REPO_ROOT / "relays" / "imessage" / "src",
]
TARGET = REPO_ROOT / "docs" / "openapi-v1.yaml"


def _stable_jsonify(value: object) -> object:
    """Round-trip through `json.dumps(sort_keys=True)` to alphabetise
    every nested-object key."""
    serialised = json.dumps(value, sort_keys=True, default=str)
    return json.loads(serialised)


def main() -> int:
    for src in SRC_PATHS:
        if str(src) not in sys.path:
            sys.path.insert(0, str(src))

    # Importing here so the sys.path tweak above is in effect.
    from bridge.main import create_app  # noqa: PLC0415

    app = create_app()
    schema = _stable_jsonify(app.openapi())

    rendered = yaml.safe_dump(
        schema,
        sort_keys=True,
        allow_unicode=True,
        default_flow_style=False,
        width=120,
    )

    TARGET.parent.mkdir(parents=True, exist_ok=True)
    TARGET.write_text(rendered, encoding="utf-8")
    sys.stdout.write(f"Wrote {TARGET.relative_to(REPO_ROOT)} ({len(rendered)} bytes)\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
