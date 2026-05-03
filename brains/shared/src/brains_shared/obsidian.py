"""Vault helpers — thin wrappers over the generated client.

Brains import these instead of reaching into ``brains_shared._generated``
directly. Each helper accepts a ``BridgeClient`` and forwards to the
generated function with a typed response.

### Why thin wrappers, not re-exports

The generated client gives us a fine-grained `sync`/`asyncio` per
endpoint. Brains generally want a higher-level "do the thing, give me
the result" call — and the vault write endpoint returns either 200
(replace/append) or 201 (create), neither of which the generator's
default parser surfaces cleanly. We use ``asyncio_detailed`` and
hand-parse the body so the helper returns a typed dataclass regardless
of status code.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, Literal

from brains_shared._generated.api.vault import (
    vault_read_v1_vault_read_get,
    vault_write_v1_vault_write_post,
)
from brains_shared._generated.models.vault_write_request import VaultWriteRequest
from brains_shared._generated.models.vault_write_request_frontmatter_type_0 import (
    VaultWriteRequestFrontmatterType0,
)
from brains_shared._generated.models.vault_write_request_mode import VaultWriteRequestMode
from brains_shared._generated.types import UNSET
from brains_shared.client import BridgeClient

WriteMode = Literal["create", "append", "replace"]

_MODE_MAP: dict[str, VaultWriteRequestMode] = {
    "create": VaultWriteRequestMode.CREATE,
    "append": VaultWriteRequestMode.APPEND,
    "replace": VaultWriteRequestMode.REPLACE,
}


@dataclass(frozen=True)
class VaultPage:
    """Result of ``read_page`` — mirrors ``VaultReadResponse``."""

    path: str
    content: str
    frontmatter: dict[str, Any] = field(default_factory=dict)
    size: int = 0
    modified_at: str = ""


@dataclass(frozen=True)
class VaultWriteOutcome:
    """Result of ``write_page`` / ``append_to_inbox``."""

    path: str
    size: int
    written_at: str
    created: bool
    """True when the bridge returned 201 (mode=create); False on 200 (replace/append)."""


async def read_page(client: BridgeClient, path: str) -> VaultPage:
    """`GET /v1/vault/read?path=…`. Raises if the page is missing."""
    resp = await vault_read_v1_vault_read_get.asyncio_detailed(
        client=client.get_inner(),
        path=path,
    )
    if resp.status_code != 200:
        raise VaultError.from_response(resp.status_code, resp.content)
    body = json.loads(resp.content.decode("utf-8"))
    return VaultPage(
        path=str(body["path"]),
        content=str(body["content"]),
        frontmatter=dict(body.get("frontmatter") or {}),
        size=int(body.get("size", 0)),
        modified_at=str(body.get("modified_at", "")),
    )


async def write_page(
    client: BridgeClient,
    *,
    path: str,
    mode: WriteMode,
    content: str,
    frontmatter: dict[str, Any] | None = None,
) -> VaultWriteOutcome:
    """`POST /v1/vault/write`.

    On `mode="create"` the bridge returns 201; on `replace`/`append`
    it returns 200. The helper surfaces both via ``VaultWriteOutcome.created``.

    Idempotency is auto-stamped by the BridgeClient transport. To pin a
    specific key (for replay-across-process semantics), wrap the call::

        from brains_shared.client import idempotency_key
        with idempotency_key("daily-2026-05-02"):
            await write_page(...)
    """
    fm = VaultWriteRequestFrontmatterType0.from_dict(frontmatter) if frontmatter else UNSET
    body = VaultWriteRequest(
        path=path,
        mode=_MODE_MAP[mode],
        content=content,
        frontmatter=fm,
    )
    resp = await vault_write_v1_vault_write_post.asyncio_detailed(
        client=client.get_inner(),
        body=body,
    )
    if resp.status_code not in (200, 201):
        raise VaultError.from_response(resp.status_code, resp.content)
    parsed = json.loads(resp.content.decode("utf-8"))
    return VaultWriteOutcome(
        path=str(parsed["path"]),
        size=int(parsed["size"]),
        written_at=str(parsed["written_at"]),
        created=resp.status_code == 201,
    )


async def append_to_inbox(
    client: BridgeClient,
    *,
    body: str,
    frontmatter: dict[str, Any] | None = None,
    today: datetime | None = None,
) -> VaultWriteOutcome:
    """Append `body` to today's Inbox note.

    The path is `Inbox/YYYY-MM-DD.md`. Frontmatter applies only on the
    first append of the day (the bridge ignores frontmatter when the
    file already exists in append mode); for v1 we forward it
    unconditionally and accept the no-op on subsequent appends.
    """
    when = today or datetime.now(UTC)
    path = f"Inbox/{when.strftime('%Y-%m-%d')}.md"
    return await write_page(
        client,
        path=path,
        mode="append",
        content=body,
        frontmatter=frontmatter,
    )


class VaultError(RuntimeError):
    """Raised when the bridge returns a non-success status from a vault call."""

    def __init__(self, *, status: int, code: str, message: str) -> None:
        super().__init__(f"vault error {status} {code}: {message}")
        self.status = status
        self.code = code
        self.message = message

    @classmethod
    def from_response(cls, status: int, content: bytes) -> VaultError:
        try:
            envelope = json.loads(content.decode("utf-8")).get("error", {})
        except (UnicodeDecodeError, json.JSONDecodeError, AttributeError):
            envelope = {}
        return cls(
            status=status,
            code=str(envelope.get("code", "unknown")),
            message=str(envelope.get("message", "")),
        )


__all__ = [
    "VaultError",
    "VaultPage",
    "VaultWriteOutcome",
    "WriteMode",
    "append_to_inbox",
    "read_page",
    "write_page",
]
