#!/usr/bin/env python3
"""Migrate the legacy `~/.openclaw/tokens.dev.json` store into macOS Keychain.

Reads the JSON store (if it exists), creates one Keychain item per entry, and
renames the JSON file to `tokens.dev.json.migrated-YYYYMMDD`. Idempotent — a
second run finds the renamed file and exits cleanly.

Limitation: the JSON store keys credentials by `sha256(token)`, not by the
plaintext token. We cannot recover the plaintext, so the legacy entries are
imported with a synthetic placeholder token equal to the digest itself. This
preserves `(actor, scopes)` so the bridge keeps recognising existing scopes
during the transition, but downstream callers will need fresh tokens via
`scripts/mint-token.py`. The transitional JSON-fallback path in `auth.py` is
the actual migration safety net for the dev environment; this script is the
clean handoff for *new* deployments.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

from bridge import keychain

DEFAULT_PATH = Path.home() / ".openclaw" / "tokens.dev.json"


def parse_args(argv: list[str]) -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument(
        "--path",
        type=Path,
        default=DEFAULT_PATH,
        help=f"legacy JSON store path (default: {DEFAULT_PATH})",
    )
    p.add_argument(
        "--dry-run",
        action="store_true",
        help="report what would be migrated without writing to Keychain",
    )
    return p.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv if argv is not None else sys.argv[1:])
    path: Path = args.path

    if not path.exists():
        sys.stderr.write(f"No legacy store at {path}; nothing to migrate.\n")
        return 0

    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        sys.stderr.write(f"ERROR: cannot read {path}: {exc}\n")
        return 1
    if not isinstance(raw, dict):
        sys.stderr.write(f"ERROR: {path} is not a JSON object.\n")
        return 1

    migrated = 0
    for digest, body in raw.items():
        if not isinstance(digest, str) or not isinstance(body, dict):
            continue
        actor = body.get("actor")
        scopes = body.get("scopes")
        if not isinstance(actor, str) or not isinstance(scopes, list):
            continue
        scope_list = [s for s in scopes if isinstance(s, str)]
        if args.dry_run:
            sys.stderr.write(f"[dry-run] would migrate actor={actor} scopes={scope_list}\n")
        else:
            # See module docstring: we cannot recover the original plaintext,
            # so the imported token equals its digest. This preserves the
            # actor/scope binding for the in-Keychain manifest. Operators
            # should rotate via scripts/rotate-token.py.
            keychain.set_credential(actor, digest, scope_list)
        migrated += 1

    if args.dry_run:
        sys.stderr.write(f"[dry-run] {migrated} entries would be migrated.\n")
        return 0

    stamp = datetime.now().strftime("%Y%m%d")
    new_path = path.with_name(f"{path.name}.migrated-{stamp}")
    if new_path.exists():
        sys.stderr.write(
            f"NOTE: {new_path} already exists; leaving JSON file in place.\n",
        )
    else:
        path.rename(new_path)
        sys.stderr.write(f"Renamed {path} -> {new_path}\n")
    sys.stderr.write(f"Migrated {migrated} entries into macOS Keychain.\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
