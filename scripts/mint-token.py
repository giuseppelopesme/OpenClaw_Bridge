#!/usr/bin/env python3
"""Mint a new bridge token for an actor and store it in macOS Keychain.

Prints the plaintext token to stdout exactly once. Never logs it. The bridge
sees the new token within `auth.REFRESH_TTL_SECONDS` (60s); pass `--touch` to
also bump the bridge's in-memory map immediately if it shares this process
(useful for tests, not for prod where the bridge runs separately).

Usage:
    scripts/mint-token.py --actor brain.clu --scopes llm:call,vault:read
"""

from __future__ import annotations

import argparse
import secrets
import sys
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


def parse_args(argv: list[str]) -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Mint a bridge token for an actor.")
    p.add_argument("--actor", required=True, help="actor id (e.g. relay.clu, brain.clu)")
    p.add_argument(
        "--scopes",
        required=True,
        help="comma-separated scope list (e.g. 'vault:read,vault:write')",
    )
    p.add_argument(
        "--bytes",
        type=int,
        default=32,
        help="random bytes of entropy in the token (default: 32)",
    )
    return p.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv if argv is not None else sys.argv[1:])
    scopes = [s.strip() for s in args.scopes.split(",") if s.strip()]
    if not scopes:
        sys.stderr.write("ERROR: at least one scope is required.\n")
        return 2

    token = secrets.token_hex(args.bytes)
    keychain.set_credential(args.actor, token, scopes)

    # Plaintext to stdout, exactly once. No structured logger here on purpose.
    sys.stdout.write(token + "\n")
    sys.stdout.flush()
    sys.stderr.write(
        f"Stored in macOS Keychain under {keychain.SERVICE_NAME} / {args.actor}.\n"
        f"Bridge will pick it up within {60}s, or restart for immediate effect.\n",
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
