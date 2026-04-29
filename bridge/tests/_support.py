"""Shared test helpers — types and the in-memory keyring fake.

Importable from any test module via `from _support import ...`. The
workspace `pythonpath` includes `bridge/tests/` so the bare-name import
works without packaging gymnastics.
"""

from __future__ import annotations

from dataclasses import dataclass

import keyring.errors


@dataclass(frozen=True)
class TokenFixture:
    plain: str
    actor: str
    scopes: tuple[str, ...]


class FakeKeyring:
    """In-memory `keyring`-shaped backend used in tests."""

    def __init__(self) -> None:
        self._store: dict[tuple[str, str], str] = {}

    def get_password(self, service: str, username: str) -> str | None:
        return self._store.get((service, username))

    def set_password(self, service: str, username: str, password: str) -> None:
        self._store[(service, username)] = password

    def delete_password(self, service: str, username: str) -> None:
        if (service, username) not in self._store:
            raise keyring.errors.PasswordDeleteError(
                f"No item for {service}/{username}",
            )
        del self._store[(service, username)]

    def reset(self) -> None:
        self._store.clear()
