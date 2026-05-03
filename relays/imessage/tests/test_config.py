"""RelayConfig.from_env — env validation and defaults."""

from __future__ import annotations

import pytest
from relay.config import RelayConfig


def test_from_env_happy_path(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: pytest.TempPathFactory,
) -> None:
    chatdb = str(tmp_path / "chat.db")
    state = str(tmp_path / "relay.state")
    monkeypatch.setenv("AGENT_NAME", "clu")
    monkeypatch.setenv("RELAY_TOKEN", "secret")
    monkeypatch.setenv("CHATDB_PATH", chatdb)
    monkeypatch.setenv("RELAY_STATE_PATH", state)
    cfg = RelayConfig.from_env()
    assert cfg.agent_name == "clu"
    assert cfg.relay_token == "secret"
    assert str(cfg.chatdb_path) == chatdb
    assert cfg.bridge_url == "http://127.0.0.1:8788"
    assert cfg.poll_interval_s == 2.0
    assert cfg.outbox_timeout_s == 25


def test_from_env_unknown_agent_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AGENT_NAME", "stranger")
    monkeypatch.setenv("RELAY_TOKEN", "t")
    with pytest.raises(ValueError):
        RelayConfig.from_env()


def test_from_env_missing_token_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AGENT_NAME", "clu")
    monkeypatch.delenv("RELAY_TOKEN", raising=False)
    with pytest.raises(ValueError):
        RelayConfig.from_env()


def test_from_env_strips_trailing_slash(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AGENT_NAME", "clu")
    monkeypatch.setenv("RELAY_TOKEN", "t")
    monkeypatch.setenv("BRIDGE_URL", "http://x:8788/")
    cfg = RelayConfig.from_env()
    assert cfg.bridge_url == "http://x:8788"
