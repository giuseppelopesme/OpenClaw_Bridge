"""Bridge runtime configuration.

Plain dataclass populated from the environment at app-creation time. No
`.env` parsing here, no pydantic-settings dep — `from_env()` reads the
documented variables from `os.environ` directly.

Field summary:

- `host`, `port`, `log_level` — uvicorn / logging knobs.
- `idempotency_db_path` — SQLite file backing the Idempotency-Key middleware.
- `telemetry_db_path` — SQLite file for LLM call telemetry.
- `access_log_path` — JSONL access log file path; daily-rotated.
- `vault_root` — Obsidian vault root (`OBSIDIAN_VAULT`). Required for vault
  endpoints; `None` when the env var is not set, in which case those routes
  return `dependency_unavailable`.

Tokens live in macOS Keychain only. The Session 1/2 transitional JSON
fallback was removed in Session 3.
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
    idempotency_db_path: Path
    telemetry_db_path: Path
    access_log_path: Path
    vault_root: Path | None

    @classmethod
    def from_env(cls) -> Settings:
        vault_raw = os.environ.get("OBSIDIAN_VAULT")
        return cls(
            host=os.environ.get("BRIDGE_HOST", "127.0.0.1"),
            port=int(os.environ.get("BRIDGE_PORT", "8788")),
            log_level=os.environ.get("BRIDGE_LOG_LEVEL", "info"),
            idempotency_db_path=Path(
                os.path.expanduser(
                    os.environ.get("BRIDGE_IDEMPOTENCY_DB", "~/.openclaw/idempotency.db"),
                ),
            ),
            telemetry_db_path=Path(
                os.path.expanduser(
                    os.environ.get("BRIDGE_TELEMETRY_DB", "~/.openclaw/telemetry.db"),
                ),
            ),
            access_log_path=Path(
                os.path.expanduser(
                    os.environ.get("BRIDGE_ACCESS_LOG", "~/.openclaw/access.log"),
                ),
            ),
            vault_root=(Path(os.path.expanduser(vault_raw)).resolve() if vault_raw else None),
        )
