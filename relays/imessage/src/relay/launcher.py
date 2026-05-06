"""In-app entrypoint for ``OpenClawRelay.app``.

PyInstaller wraps this module's ``main()`` as the bundle's
``Contents/MacOS/OpenClawRelay`` binary. The launcher's only jobs:

1. Resolve two independent identifiers:
     - ``AGENT_NAME`` — the brain this relay routes to. The bundled
       LaunchAgent's ``EnvironmentVariables`` block sets it (default
       ``agent`` — the brain package's default identifier). We only
       read the env var here; ``relay.config.from_env`` is the validator.
     - The macOS account name that runs this relay — ``getpass.getuser()``.
       Independent of AGENT_NAME so the operator can name their service
       user anything they like (the installer is account-agnostic).
2. Build the Keychain actor key as ``relay.<service-user-account>``,
   matching what the pkg postinstall plants in that user's login
   keychain. Read ``RELAY_TOKEN`` via ``relay.keychain_reader`` and
   inject it into the env. Fail-loud with a structured error if missing.
3. Hand off to ``relay.main.main()``, which is unchanged from the
   pre-bundle topology — it reads its config from the env we just
   populated. Same code path, different parent process.
"""

from __future__ import annotations

import getpass
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


def _resolve_service_user() -> str:
    """The macOS account name that runs this relay process.

    This is the *account-side* identity — what the postinstall hands
    to ``relay.<account>`` when it plants the auth token in the user's
    login keychain. Always derived from the OS at runtime; never read
    from an env var, because the env var would let the relay
    misidentify itself if it ever escaped its launchd domain.
    """
    return getpass.getuser()


def _redirect_stdio_to_log_files(service_user: str) -> None:
    """Redirect stdout/stderr to ``~/.openclaw/relay.<account>.{out,err}.log``.

    Mirrors the supervisor's redirect (see ``bridge.supervisor``).
    The bundled LaunchAgent plist deliberately omits ``StandardOutPath``
    / ``StandardErrorPath`` because launchd does not expand ``~``.
    Only redirects when running under launchd / a frozen .app — dev
    invocations inherit the operator's terminal.

    Log filenames key on the running account (not the brain identity),
    so multi-relay setups on the same Mac don't collide and each
    operator sees logs for their own relay under their own home.
    """
    if not getattr(sys, "frozen", False):
        return
    log_dir = os.path.join(os.path.expanduser("~"), ".openclaw")
    os.makedirs(log_dir, exist_ok=True)
    out_path = os.path.join(log_dir, f"relay.{service_user}.out.log")
    err_path = os.path.join(log_dir, f"relay.{service_user}.err.log")
    out_fd = os.open(out_path, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o644)
    err_fd = os.open(err_path, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o644)
    os.dup2(out_fd, 1)
    os.dup2(err_fd, 2)
    os.close(out_fd)
    os.close(err_fd)
    sys.stdout = os.fdopen(1, "w", buffering=1, encoding="utf-8")
    sys.stderr = os.fdopen(2, "w", buffering=1, encoding="utf-8")


def main() -> int:
    service_user = _resolve_service_user()
    _redirect_stdio_to_log_files(service_user)
    actor = f"relay.{service_user}"

    if not os.environ.get("RELAY_TOKEN", "").strip():
        try:
            token = read_relay_token(actor)
        except KeychainReadError as exc:
            _emit_fatal(
                "relay_launcher_keychain_read_failed",
                actor=actor,
                service_user=service_user,
                error=str(exc),
                hint=(
                    f"Store the token for actor '{actor}' in the running "
                    "user's login keychain. The pkg installer normally "
                    "handles this; or directly: "
                    f"security add-generic-password -U "
                    f"-s me.lopes.openclaw.bridge -a {actor} "
                    '-w \'{"token":"...","scopes":["imessage:relay"]}\''
                ),
            )
            return 2
        os.environ["RELAY_TOKEN"] = token

    return relay_main()


if __name__ == "__main__":
    raise SystemExit(main())
