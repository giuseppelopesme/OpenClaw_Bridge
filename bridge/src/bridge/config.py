"""Bridge runtime configuration.

Plain dataclass populated from the environment at app-creation time. No
`.env` parsing here, no pydantic-settings dep — `from_env()` reads the
documented variables from `os.environ` directly.

Field summary:

- `host`, `port`, `log_level` — uvicorn / logging knobs.
- `token_store_path` — legacy JSON fallback path. Tokens primarily live in
  macOS Keychain; this path is only consulted when Keychain enumeration
  returns zero credentials. Removed in Session 3.
- `idempotency_db_path` — SQLite file backing the Idempotency-Key middleware.
- `vault_root` — Obsidian vault root (`OBSIDIAN_VAULT`). Required for vault
  endpoints; `None` when the env var is not set, in which case those routes
  return `dependency_unavailable`.
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
    idempotency_db_path: Path
    vault_root: Path | None

    @classmethod
    def from_env(cls) -> Settings:
        vault_raw = os.environ.get("OBSIDIAN_VAULT")
        return cls(
            host=os.environ.get("BRIDGE_HOST", "127.0.0.1"),
            port=int(os.environ.get("BRIDGE_PORT", "8788")),
            log_level=os.environ.get("BRIDGE_LOG_LEVEL", "info"),
            token_store_path=Path(
                os.path.expanduser(
                    os.environ.get("BRIDGE_TOKEN_STORE", "~/.openclaw/tokens.dev.json"),
                ),
            ),
            idempotency_db_path=Path(
                os.path.expanduser(
                    os.environ.get("BRIDGE_IDEMPOTENCY_DB", "~/.openclaw/idempotency.db"),
                ),
            ),
            vault_root=(Path(os.path.expanduser(vault_raw)).resolve() if vault_raw else None),
        )
