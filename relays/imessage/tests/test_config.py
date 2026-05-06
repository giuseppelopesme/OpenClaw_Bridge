"""RelayConfig.from_env — env validation and defaults.

Critical invariants:
  - AGENT_NAME is the BRAIN's free-form identifier. When unset, falls
    back to ``DEFAULT_AGENT_NAME`` ("agent") — NOT to the running
    user's account name. The bug this guards against: earlier versions
    defaulted to ``getpass.getuser()``, which crashed the relay if the
    operator's service user account name wasn't a valid agent name.
  - The agent name is validated as a well-formed identifier (lowercase
    letter / digit / underscore, length 1–32). Garbage env values
    (whitespace, special chars, oversized strings) raise loud at
    startup rather than silently mis-route.
"""

from __future__ import annotations

import pytest
from relay.config import DEFAULT_AGENT_NAME, RelayConfig


def test_from_env_happy_path(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: pytest.TempPathFactory,
) -> None:
    chatdb = str(tmp_path / "chat.db")
    state = str(tmp_path / "relay.state")
    monkeypatch.setenv("AGENT_NAME", "agent")
    monkeypatch.setenv("RELAY_TOKEN", "secret")
    monkeypatch.setenv("CHATDB_PATH", chatdb)
    monkeypatch.setenv("RELAY_STATE_PATH", state)
    cfg = RelayConfig.from_env()
    assert cfg.agent_name == "agent"
    assert cfg.relay_token == "secret"
    assert str(cfg.chatdb_path) == chatdb
    assert cfg.bridge_url == "http://127.0.0.1:8788"
    assert cfg.poll_interval_s == 2.0
    assert cfg.outbox_timeout_s == 25


@pytest.mark.parametrize(
    "bad",
    [
        "Agent",  # uppercase
        "1agent",  # digit-leading
        "ag-ent",  # hyphen
        "ag ent",  # space
        "ag.ent",  # dot
        "x" * 33,  # too long
        "_leading",  # leading underscore (regex requires letter first)
    ],
)
def test_from_env_malformed_agent_rejected(
    monkeypatch: pytest.MonkeyPatch,
    bad: str,
) -> None:
    """Bad AGENT_NAME values raise loud at startup."""
    monkeypatch.setenv("AGENT_NAME", bad)
    monkeypatch.setenv("RELAY_TOKEN", "t")
    with pytest.raises(ValueError):
        RelayConfig.from_env()


def test_from_env_accepts_custom_well_formed_agent(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Operators can name their brain anything well-formed."""
    monkeypatch.setenv("AGENT_NAME", "my_assistant")
    monkeypatch.setenv("RELAY_TOKEN", "t")
    cfg = RelayConfig.from_env()
    assert cfg.agent_name == "my_assistant"


def test_from_env_missing_token_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AGENT_NAME", "agent")
    monkeypatch.delenv("RELAY_TOKEN", raising=False)
    with pytest.raises(ValueError):
        RelayConfig.from_env()


def test_from_env_strips_trailing_slash(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AGENT_NAME", "agent")
    monkeypatch.setenv("RELAY_TOKEN", "t")
    monkeypatch.setenv("BRIDGE_URL", "http://x:8788/")
    cfg = RelayConfig.from_env()
    assert cfg.bridge_url == "http://x:8788"


def test_from_env_defaults_when_agent_name_unset(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """AGENT_NAME default = DEFAULT_AGENT_NAME, not getpass.getuser().

    Earlier versions defaulted to the running user's account name,
    which crashed the relay if the service user wasn't named after the
    locked agent set. The relay binary is account-agnostic; AGENT_NAME
    is a separate concept (which brain, not which OS account).
    """
    monkeypatch.delenv("AGENT_NAME", raising=False)
    monkeypatch.setenv("RELAY_TOKEN", "t")
    cfg = RelayConfig.from_env()
    assert cfg.agent_name == DEFAULT_AGENT_NAME


def test_from_env_empty_agent_name_uses_default(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An empty-string AGENT_NAME (whitespace-only) is treated as unset."""
    monkeypatch.setenv("AGENT_NAME", "   ")
    monkeypatch.setenv("RELAY_TOKEN", "t")
    cfg = RelayConfig.from_env()
    assert cfg.agent_name == DEFAULT_AGENT_NAME
