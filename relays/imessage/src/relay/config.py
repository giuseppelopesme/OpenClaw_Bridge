"""Env-driven runtime configuration for the relay.

Mirrors the bridge's ``Settings`` shape (frozen dataclass, ``from_env``
factory) for consistency. None of these values are secrets; the relay
token is the only sensitive item and ``RELAY_TOKEN`` is expected to be
plumbed in via launchd's ``EnvironmentVariables`` block (the bundled
LaunchAgent template at
``Contents/Library/LaunchAgents/me.lopes.openclaw.relay.plist`` inside
``OpenClawRelay.app``).

A token is minted with::

    uv run --no-sync python scripts/mint-token.py \\
        --actor relay.<service-user-account> --scopes imessage:relay

where ``<service-user-account>`` is the macOS account name that runs
this relay process — i.e. ``getpass.getuser()`` at runtime. That account
is independent of ``AGENT_NAME``: the agent name is the brain's
identifier (a free-form well-formed token), while the keychain actor
key is parametric on whichever macOS user happens to host the relay.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass
from pathlib import Path

# Default brain identifier when AGENT_NAME is not set in the env.
# The shipped brain implementation lives in ``brains/agent/``; operators
# customising the brain (different persona, prompts, tooling) typically
# keep the same default and override only the runtime config.
DEFAULT_AGENT_NAME = "agent"

# Well-formed agent identifier: lowercase Python-identifier-like token.
# Kept narrow so it composes cleanly into Redis topic names, SQLite
# filenames, and Keychain account keys without quoting.
_AGENT_NAME_RE = re.compile(r"^[a-z][a-z0-9_]{0,31}$")


@dataclass(frozen=True)
class RelayConfig:
    bridge_url: str
    agent_name: str
    relay_token: str
    chatdb_path: Path
    state_path: Path
    poll_interval_s: float
    outbox_timeout_s: int

    @classmethod
    def from_env(cls) -> RelayConfig:
        # AGENT_NAME = brain identifier. Defaults to DEFAULT_AGENT_NAME
        # when unset; this is independent of which macOS user account
        # runs the relay (so an operator whose service account is e.g.
        # "pippo" still routes to the brain named "agent").
        agent = os.environ.get("AGENT_NAME", "").strip() or DEFAULT_AGENT_NAME
        if not _AGENT_NAME_RE.match(agent):
            raise ValueError(
                f"AGENT_NAME must match {_AGENT_NAME_RE.pattern}; got {agent!r}.",
            )
        token = os.environ.get("RELAY_TOKEN", "").strip()
        if not token:
            raise ValueError(
                "RELAY_TOKEN must be set (mint with scripts/mint-token.py).",
            )
        chatdb_raw = os.environ.get("CHATDB_PATH", "~/Library/Messages/chat.db")
        state_raw = os.environ.get(
            "RELAY_STATE_PATH",
            f"~/.openclaw/relay.{agent}.state",
        )
        return cls(
            bridge_url=os.environ.get("BRIDGE_URL", "http://127.0.0.1:8788").rstrip("/"),
            agent_name=agent,
            relay_token=token,
            chatdb_path=Path(os.path.expanduser(chatdb_raw)),
            state_path=Path(os.path.expanduser(state_raw)),
            poll_interval_s=float(os.environ.get("POLL_INTERVAL_S", "2.0")),
            outbox_timeout_s=int(os.environ.get("OUTBOX_TIMEOUT_S", "25")),
        )
