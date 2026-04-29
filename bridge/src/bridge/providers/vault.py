"""Filesystem provider for the Obsidian vault.

The vault is the canonical Obsidian directory pointed to by `OBSIDIAN_VAULT`.
Every requested path is resolved against the vault root with `Path.resolve()`
and rejected if it escapes the root, contains symlinks pointing outside the
root, or is absolute.

Frontmatter parsing/serialisation uses `python-frontmatter`. Field order in
the YAML block is preserved across a round-trip.

Contracts:

- `read(path)` returns content (markdown body without frontmatter), parsed
  frontmatter dict, and stat metadata.
- `write(path, mode, content, frontmatter)` honours `create | append | replace`
  per `docs/api-contract.md`. `append` creates the file if missing; `create`
  raises `Conflict` if it exists; `replace` raises `NotFound` if it does not.
- All path-traversal attempts raise `BadRequest` with `details.path`.

This module deliberately knows nothing about HTTP — routes do the
serialisation. That keeps the provider easy to drive from CLIs and brains.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Final, Literal

import frontmatter

from bridge.errors import BadRequest, Conflict, DependencyUnavailable, NotFound

WriteMode = Literal["create", "append", "replace"]

_ALLOWED_MODES: Final[frozenset[str]] = frozenset({"create", "append", "replace"})


@dataclass(frozen=True)
class VaultRead:
    path: str
    content: str
    frontmatter: dict[str, Any]
    size: int
    modified_at: str


@dataclass(frozen=True)
class VaultWriteResult:
    path: str
    size: int
    written_at: str
    op: WriteMode


class VaultProvider:
    """Bound to a single vault root. Construct once at app startup."""

    def __init__(self, root: Path | None) -> None:
        self._root_raw: Path | None = root

    @property
    def configured(self) -> bool:
        return self._root_raw is not None

    @property
    def root(self) -> Path:
        if self._root_raw is None:
            raise DependencyUnavailable(
                "Vault is not configured (OBSIDIAN_VAULT unset).",
            )
        return self._root_raw

    # -- path safety -------------------------------------------------------

    def resolve(self, rel_path: str) -> Path:
        """Resolve `rel_path` against the vault root. Raise on traversal.

        Rejects:
        - empty paths
        - absolute paths (anything starting with `/`)
        - paths that resolve outside the vault root (covers `..` and symlinks
          pointing outside the root, since `Path.resolve()` follows them)
        """
        if not rel_path or not rel_path.strip():
            raise BadRequest("Vault path must be non-empty.")
        if rel_path.startswith("/") or os.path.isabs(rel_path):
            raise BadRequest(
                "Vault path must be relative to the vault root.",
                details={"path": rel_path},
            )
        candidate = (self.root / rel_path).resolve()
        try:
            candidate.relative_to(self.root)
        except ValueError as exc:
            raise BadRequest(
                "Vault path escapes the vault root.",
                details={"path": rel_path},
            ) from exc
        return candidate

    # -- read --------------------------------------------------------------

    def read(self, rel_path: str) -> VaultRead:
        target = self.resolve(rel_path)
        if not target.exists() or not target.is_file():
            raise NotFound(
                f"Vault path does not exist: {rel_path}",
                details={"path": rel_path},
            )
        post = frontmatter.load(str(target))
        stat = target.stat()
        return VaultRead(
            path=rel_path,
            content=post.content,
            frontmatter=dict(post.metadata),
            size=stat.st_size,
            modified_at=datetime.fromtimestamp(stat.st_mtime, tz=UTC).isoformat(),
        )

    # -- write -------------------------------------------------------------

    def write(
        self,
        rel_path: str,
        *,
        mode: WriteMode,
        content: str,
        frontmatter_data: dict[str, Any] | None = None,
    ) -> VaultWriteResult:
        if mode not in _ALLOWED_MODES:
            raise BadRequest(
                f"Unknown write mode: {mode!r}",
                details={"mode": mode, "allowed": sorted(_ALLOWED_MODES)},
            )
        target = self.resolve(rel_path)
        exists = target.exists()
        if mode == "create" and exists:
            raise Conflict(
                f"Vault path already exists: {rel_path}",
                details={"path": rel_path, "mode": mode},
            )
        if mode == "replace" and not exists:
            raise NotFound(
                f"Vault path does not exist: {rel_path}",
                details={"path": rel_path, "mode": mode},
            )

        target.parent.mkdir(parents=True, exist_ok=True)

        if mode == "append":
            self._do_append(target, content)
        else:
            self._do_create_or_replace(target, content, frontmatter_data)

        stat = target.stat()
        return VaultWriteResult(
            path=rel_path,
            size=stat.st_size,
            written_at=datetime.fromtimestamp(stat.st_mtime, tz=UTC).isoformat(),
            op=mode,
        )

    @staticmethod
    def _do_append(target: Path, content: str) -> None:
        # Append plain content to whatever exists. Frontmatter on append is
        # not supported in v1 — appending re-parsed frontmatter would surprise
        # callers who expect their content to land at end-of-file.
        prefix = ""
        if target.exists() and target.stat().st_size > 0:
            with target.open("rb") as fh:
                fh.seek(-1, 2)
                last = fh.read(1)
            if last not in (b"\n", b""):
                prefix = "\n"
        with target.open("a", encoding="utf-8") as fh:
            fh.write(prefix + content)

    @staticmethod
    def _do_create_or_replace(
        target: Path,
        content: str,
        frontmatter_data: dict[str, Any] | None,
    ) -> None:
        if frontmatter_data:
            post = frontmatter.Post(content, **frontmatter_data)
            # `sort_keys=False` is forwarded to PyYAML so the field order on
            # disk matches the order callers passed in. Otherwise PyYAML's
            # default sorts alphabetically and surprises Obsidian users.
            payload = frontmatter.dumps(post, sort_keys=False)
        else:
            payload = content
        if not payload.endswith("\n"):
            payload += "\n"
        target.write_text(payload, encoding="utf-8")
