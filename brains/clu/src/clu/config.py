"""CLU runtime configuration. Frozen dataclass populated from env.

Mirrors the shape of `relay/config.py` (Session 7) — same naming
conventions, same fail-loud-on-missing-token policy. Env vars:

- ``BRIDGE_URL`` (default ``http://127.0.0.1:8788``)
- ``BRAIN_TOKEN`` (required) — bearer token minted via
  ``scripts/mint-token.py --actor brain.clu --scopes
  llm:call,vault:read,vault:write,events:subscribe,events:publish,imessage:send``
- ``STATE_DB_PATH`` (default ``~/.openclaw/clu.state.db``) — SQLite
  file backing the dedup map and the pending-draft store.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class CluConfig:
    bridge_url: str
    brain_token: str
    state_db_path: Path

    @classmethod
    def from_env(cls) -> CluConfig:
        token = os.environ.get("BRAIN_TOKEN", "").strip()
        if not token:
            raise ValueError(
                "BRAIN_TOKEN must be set (mint with scripts/mint-token.py).",
            )
        return cls(
            bridge_url=os.environ.get("BRIDGE_URL", "http://127.0.0.1:8788").rstrip("/"),
            brain_token=token,
            state_db_path=Path(
                os.path.expanduser(
                    os.environ.get("STATE_DB_PATH", "~/.openclaw/clu.state.db"),
                ),
            ),
        )
