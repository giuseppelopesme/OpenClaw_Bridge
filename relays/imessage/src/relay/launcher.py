"""In-app entrypoint for ``OpenClawRelay.app``.

PyInstaller wraps this module's ``main()`` as the bundle's
``Contents/MacOS/OpenClawRelay`` binary. The launcher's only jobs:

1. Resolve ``AGENT_NAME`` (defaults to ``clu`` — the bundle is per-agent,
   one .app per service-account macOS user).
2. Read ``RELAY_TOKEN`` from the running user's login keychain via
   ``security find-generic-password`` (see ``relay.keychain_reader``).
   Fail-loud with a structured error if missing — the operator's
   ``setup-clu-account.sh`` is the documented way to populate the slot.
3. Hand off to ``relay.main.main()``, which is unchanged from the
   pre-bundle topology — it reads its config from the env we just
   populated. Same code path, different parent process.

The .app's launchd plist (bundled inside ``Contents/Library/LaunchAgents``,
copied into ``~/Library/LaunchAgents`` by the install script) sets
``BRIDGE_URL`` and ``AGENT_NAME`` via ``EnvironmentVariables``; this
launcher only fills the gap that the old ``scripts/run-relay.sh``
filled — the keychain-sourced bearer token.
"""

from __future__ import annotations

import json
import logging
import os
import sys
from datetime import UTC, datetime

from relay.keychain_reader import KeychainReadError, read_relay_token
from relay.main import main as relay_main

logger = logging.getLogger("relay.launcher")


def _emit_fatal(event: str, **fields: object) -> None:
    """Write one structured JSON line to stderr and bail.

    The relay's normal logging is configured inside ``relay.main._setup_logging``,
    but this launcher runs *before* that — so we hand-format the same
    shape (ts/level/logger/msg) to keep launchd's log file readable.
    """
    body: dict[str, object] = {
        "ts": datetime.now(UTC).isoformat(),
        "level": "error",
        "logger": "relay.launcher",
        "msg": event,
    }
    body.update(fields)
    sys.stderr.write(json.dumps(body, default=str) + "\n")
    sys.stderr.flush()


def main() -> int:
    agent = os.environ.get("AGENT_NAME", "clu").strip() or "clu"
    actor = f"relay.{agent}"

    if not os.environ.get("RELAY_TOKEN", "").strip():
        try:
            token = read_relay_token(actor)
        except KeychainReadError as exc:
            _emit_fatal(
                "relay_launcher_keychain_read_failed",
                actor=actor,
                error=str(exc),
                hint=(
                    "Run scripts/setup-clu-account.sh on this account, "
                    "or store the token manually with: "
                    f"security add-generic-password -U "
                    f"-s com.giuseppelopesme.openclaw.bridge -a {actor} "
                    '-w \'{"token":"...","scopes":["imessage:relay"]}\''
                ),
            )
            return 2
        os.environ["RELAY_TOKEN"] = token

    return relay_main()


if __name__ == "__main__":
    raise SystemExit(main())
