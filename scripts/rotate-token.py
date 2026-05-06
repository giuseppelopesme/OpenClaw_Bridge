#!/usr/bin/env python3
"""Rotate the token for an existing actor.

Issues a fresh token; the prior token stays valid for 24h via the
`previous_token` / `previous_expires_at` fields. Scopes are preserved unless
`--scopes` is supplied (which fully replaces them).

Usage:
    scripts/rotate-token.py --actor brain.agent
    scripts/rotate-token.py --actor brain.agent --scopes vault:read,vault:write
    scripts/rotate-token.py --actor brain.agent --grace-hours 24
"""

from __future__ import annotations

import argparse
import secrets
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

# Self-bootstrap workspace src dirs onto sys.path so this script runs
# without an explicit `PYTHONPATH=bridge/src` prefix. Workaround for the
# uv 0.11.x hidden-`.pth` interaction with Python 3.13's site.py
# (documented in Session 1's SESSION-NOTES.md).
_REPO_ROOT = Path(__file__).resolve().parent.parent
_BRIDGE_SRC = _REPO_ROOT / "bridge" / "src"
if str(_BRIDGE_SRC) not in sys.path:
    sys.path.insert(0, str(_BRIDGE_SRC))

from bridge import keychain  # noqa: E402

DEFAULT_GRACE_HOURS = 24


def parse_args(argv: list[str]) -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Rotate a bridge token for an actor.")
    p.add_argument("--actor", required=True)
    p.add_argument(
        "--scopes",
        default=None,
        help="optional comma-separated scope list; preserves existing scopes if omitted",
    )
    p.add_argument("--bytes", type=int, default=32)
    p.add_argument(
        "--grace-hours",
        type=int,
        default=DEFAULT_GRACE_HOURS,
        help=f"hours the previous token stays valid (default: {DEFAULT_GRACE_HOURS})",
    )
    return p.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv if argv is not None else sys.argv[1:])
    existing = keychain.get_credential(args.actor)
    if existing is None:
        sys.stderr.write(
            f"ERROR: no credential for actor {args.actor!r}. Mint one first.\n",
        )
        return 1

    if args.scopes is None:
        scopes = list(existing.scopes)
    else:
        scopes = [s.strip() for s in args.scopes.split(",") if s.strip()]
        if not scopes:
            sys.stderr.write("ERROR: --scopes was supplied but empty.\n")
            return 2

    new_token = secrets.token_hex(args.bytes)
    expires_at = datetime.now(UTC) + timedelta(hours=args.grace_hours)
    keychain.set_credential(
        args.actor,
        new_token,
        scopes,
        previous_token=existing.token,
        previous_expires_at=expires_at,
    )

    sys.stdout.write(new_token + "\n")
    sys.stdout.flush()
    sys.stderr.write(
        f"Rotated token for {args.actor!r}. Previous token valid until {expires_at.isoformat()}.\n",
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
