"""Agent runtime configuration. Frozen dataclass populated from env.

Mirrors the shape of ``relay/config.py`` — same naming conventions,
same fail-loud-on-missing-token policy. Env vars:

- ``BRIDGE_URL`` (default ``http://127.0.0.1:8788``)
- ``AGENT_NAME`` (default ``agent``) — the brain's public identifier.
  Used in topic names (``imessage.received.{agent}``,
  ``agent.{agent}.draft.pending``), state-DB filename, and the
  Keychain actor key (``brain.{agent}``). Operators choose a name when
  customising; the default ``agent`` is fine for single-brain installs.
- ``BRAIN_TOKEN`` (required) — bearer token minted via
  ``scripts/mint-token.py --actor brain.{agent} --scopes
  llm:call,vault:read,vault:write,events:subscribe,events:publish,imessage:send``
- ``STATE_DB_PATH`` (default ``~/.openclaw/{agent}.state.db``) —
  SQLite file backing the dedup map and the pending-draft store.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass
from pathlib import Path

DEFAULT_AGENT_NAME = "agent"

# A well-formed agent identifier: a Python identifier-like token, kept
# narrow so it composes cleanly into Redis topic names, SQLite filenames,
# and Keychain account keys without quoting. Operators picking exotic
# names should pick something that fits.
_AGENT_NAME_RE = re.compile(r"^[a-z][a-z0-9_]{0,31}$")


@dataclass(frozen=True)
class AgentConfig:
    bridge_url: str
    agent_name: str
    brain_token: str
    state_db_path: Path

    @classmethod
    def from_env(cls) -> AgentConfig:
        agent_name = os.environ.get("AGENT_NAME", "").strip() or DEFAULT_AGENT_NAME
        if not _AGENT_NAME_RE.match(agent_name):
            raise ValueError(
                f"AGENT_NAME must match {_AGENT_NAME_RE.pattern}; got {agent_name!r}.",
            )
        token = os.environ.get("BRAIN_TOKEN", "").strip()
        if not token:
            raise ValueError(
                "BRAIN_TOKEN must be set (mint with scripts/mint-token.py).",
            )
        default_state_db = f"~/.openclaw/{agent_name}.state.db"
        return cls(
            bridge_url=os.environ.get("BRIDGE_URL", "http://127.0.0.1:8788").rstrip("/"),
            agent_name=agent_name,
            brain_token=token,
            state_db_path=Path(
                os.path.expanduser(
                    os.environ.get("STATE_DB_PATH", default_state_db),
                ),
            ),
        )
