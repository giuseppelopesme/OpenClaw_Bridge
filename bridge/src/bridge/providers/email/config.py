"""TOML loader for `~/.openclaw/email.toml`.

The file looks like:

    [accounts.glysk]
    address = "giuseppe@glysk.dev"
    imap_host = "imap.fastmail.com"
    imap_port = 993
    smtp_host = "smtp.fastmail.com"
    smtp_port = 587

    [accounts.lopes]
    ...

Server names are not secrets, passwords are. Passwords live in macOS
Keychain under `provider.email.{account}` (one item per account, password
field is the plaintext IMAP+SMTP password).

If the file is missing or malformed, `load_email_config` returns an empty
config and the bridge logs a structured warning at startup. Email routes
then return 502 `dependency_unavailable` until config is fixed.
"""

from __future__ import annotations

import logging
import tomllib
from dataclasses import dataclass
from pathlib import Path

from bridge.providers.email.models import EmailAccount

logger = logging.getLogger("bridge.providers.email.config")

ALLOWED_ACCOUNTS: frozenset[str] = frozenset({"glysk", "lopes", "whilesum"})


@dataclass(frozen=True)
class EmailConfig:
    """Parsed `email.toml`. Empty accounts dict = unconfigured."""

    accounts: dict[str, EmailAccount]

    @property
    def configured(self) -> bool:
        return bool(self.accounts)

    def get(self, name: str) -> EmailAccount | None:
        return self.accounts.get(name)


def load_email_config(path: Path) -> EmailConfig:
    """Load and validate the email config. Never raises on missing file."""
    if not path.exists():
        logger.info(
            "email_config_missing",
            extra={"path": str(path)},
        )
        return EmailConfig(accounts={})
    try:
        with path.open("rb") as fh:
            raw = tomllib.load(fh)
    except (OSError, tomllib.TOMLDecodeError) as exc:
        logger.warning(
            "email_config_unreadable",
            extra={"path": str(path), "error": str(exc)},
        )
        return EmailConfig(accounts={})

    accounts: dict[str, EmailAccount] = {}
    raw_accounts = raw.get("accounts", {})
    if not isinstance(raw_accounts, dict):
        logger.warning(
            "email_config_malformed",
            extra={"path": str(path), "reason": "[accounts] is not a table"},
        )
        return EmailConfig(accounts={})

    for name, data in raw_accounts.items():
        if name not in ALLOWED_ACCOUNTS:
            logger.warning(
                "email_config_unknown_account",
                extra={"account": name, "allowed": sorted(ALLOWED_ACCOUNTS)},
            )
            continue
        try:
            accounts[name] = EmailAccount(
                name=name,
                address=str(data["address"]),
                imap_host=str(data["imap_host"]),
                imap_port=int(data.get("imap_port", 993)),
                smtp_host=str(data["smtp_host"]),
                smtp_port=int(data.get("smtp_port", 587)),
            )
        except (KeyError, TypeError, ValueError) as exc:
            logger.warning(
                "email_config_account_invalid",
                extra={"account": name, "error": str(exc)},
            )
            continue

    return EmailConfig(accounts=accounts)
