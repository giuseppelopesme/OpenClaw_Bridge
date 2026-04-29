"""Production entrypoint: `uv run python -m bridge`.

Configures JSON logging, then hands control to uvicorn. Use this in launchd /
systemd-style runners. Direct `uvicorn bridge.main:app` also works for quick
smoke tests but skips the JSON logging setup.
"""

from __future__ import annotations

import uvicorn

from bridge.config import Settings
from bridge.logging_setup import configure_logging
from bridge.main import app
from bridge.telemetry import setup_access_log


def main() -> None:
    cfg = Settings.from_env()
    configure_logging(cfg.log_level)
    # JSONL access log file (daily-rotated, 30-day retention). Tests do not
    # call this — they assert the structured `bridge.access` records via caplog.
    setup_access_log(cfg.access_log_path)
    uvicorn.run(
        app,
        host=cfg.host,
        port=cfg.port,
        # Let our JsonFormatter handle every log line; suppress uvicorn's own.
        log_config=None,
        access_log=False,
    )


if __name__ == "__main__":
    main()
