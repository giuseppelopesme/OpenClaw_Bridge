"""Bridge runtime configuration.

Step 1 deliberately keeps this tiny: read a handful of env vars at app-creation
time. No `.env` parsing, no pydantic-settings dep. Real macOS Keychain integration
for token storage lands in a later step.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Settings:
    host: str
    port: int
    log_level: str
    token_store_path: Path

    @classmethod
    def from_env(cls) -> Settings:
        return cls(
            host=os.environ.get("BRIDGE_HOST", "127.0.0.1"),
            port=int(os.environ.get("BRIDGE_PORT", "8788")),
            log_level=os.environ.get("BRIDGE_LOG_LEVEL", "info"),
            token_store_path=Path(
                os.path.expanduser(
                    os.environ.get("BRIDGE_TOKEN_STORE", "~/.openclaw/tokens.dev.json"),
                ),
            ),
        )
