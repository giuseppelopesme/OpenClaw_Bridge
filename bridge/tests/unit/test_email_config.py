"""Email TOML config loader."""

from __future__ import annotations

from pathlib import Path

from bridge.providers.email.config import load_email_config


def _write_toml(path: Path, body: str) -> None:
    path.write_text(body, encoding="utf-8")


def test_load_email_config_missing_file_returns_empty(tmp_path: Path) -> None:
    cfg = load_email_config(tmp_path / "nope.toml")
    assert cfg.accounts == {}
    assert cfg.configured is False


def test_load_email_config_happy_path(tmp_path: Path) -> None:
    p = tmp_path / "email.toml"
    _write_toml(
        p,
        """
        [accounts.glysk]
        address = "giuseppe@glysk.dev"
        imap_host = "imap.fastmail.com"
        imap_port = 993
        smtp_host = "smtp.fastmail.com"
        smtp_port = 587

        [accounts.lopes]
        address = "giuseppe@lopes.me"
        imap_host = "imap.fastmail.com"
        smtp_host = "smtp.fastmail.com"
        """,
    )
    cfg = load_email_config(p)
    assert cfg.configured
    assert set(cfg.accounts.keys()) == {"glysk", "lopes"}
    glysk = cfg.accounts["glysk"]
    assert glysk.address == "giuseppe@glysk.dev"
    assert glysk.imap_port == 993
    assert glysk.smtp_port == 587
    # Defaults when fields are omitted.
    assert cfg.accounts["lopes"].imap_port == 993
    assert cfg.accounts["lopes"].smtp_port == 587


def test_load_email_config_unknown_account_is_dropped(tmp_path: Path) -> None:
    p = tmp_path / "email.toml"
    _write_toml(
        p,
        """
        [accounts.fancy]
        address = "x@y.z"
        imap_host = "h"
        smtp_host = "h"
        """,
    )
    cfg = load_email_config(p)
    assert cfg.accounts == {}


def test_load_email_config_account_missing_required_field(tmp_path: Path) -> None:
    p = tmp_path / "email.toml"
    _write_toml(
        p,
        """
        [accounts.glysk]
        imap_host = "h"
        smtp_host = "h"
        """,
    )
    cfg = load_email_config(p)
    assert "glysk" not in cfg.accounts


def test_load_email_config_malformed_toml(tmp_path: Path) -> None:
    p = tmp_path / "email.toml"
    p.write_text("this is not valid toml [", encoding="utf-8")
    cfg = load_email_config(p)
    assert cfg.accounts == {}
