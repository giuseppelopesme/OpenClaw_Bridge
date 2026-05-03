"""Env-driven runtime configuration for the relay.

Mirrors the bridge's ``Settings`` shape (frozen dataclass, ``from_env``
factory) for consistency. None of these values are secrets; the relay
token is the only sensitive item and ``RELAY_TOKEN`` is expected to be
plumbed in via launchd's ``EnvironmentVariables`` block (see
``ops/launchd/com.giuseppelopesme.openclaw.relay.clu.plist``).

A token is minted with::

    uv run --no-sync python scripts/mint-token.py \\
        --actor relay.clu --scopes imessage:relay
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

AgentName = Literal["clu", "tron", "flynn"]
_ALLOWED_AGENTS: frozenset[str] = frozenset({"clu", "tron", "flynn"})


@dataclass(frozen=True)
class RelayConfig:
    bridge_url: str
    agent_name: AgentName
    relay_token: str
    chatdb_path: Path
    state_path: Path
    poll_interval_s: float
    outbox_timeout_s: int

    @classmethod
    def from_env(cls) -> RelayConfig:
        agent = os.environ.get("AGENT_NAME", "clu")
        if agent not in _ALLOWED_AGENTS:
            raise ValueError(
                f"AGENT_NAME must be one of {sorted(_ALLOWED_AGENTS)}; got {agent!r}.",
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
            agent_name=agent,  # type: ignore[arg-type]
            relay_token=token,
            chatdb_path=Path(os.path.expanduser(chatdb_raw)),
            state_path=Path(os.path.expanduser(state_raw)),
            poll_interval_s=float(os.environ.get("POLL_INTERVAL_S", "2.0")),
            outbox_timeout_s=int(os.environ.get("OUTBOX_TIMEOUT_S", "25")),
        )
