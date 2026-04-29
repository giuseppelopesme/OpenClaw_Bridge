"""VaultProvider: read, three write modes, path safety, frontmatter round-trip."""

from __future__ import annotations

from pathlib import Path

import pytest
from bridge.errors import BadRequest, Conflict, NotFound
from bridge.providers.vault import VaultProvider


@pytest.fixture
def provider(vault_root: Path) -> VaultProvider:
    return VaultProvider(vault_root)


def test_read_returns_body_frontmatter_and_metadata(provider: VaultProvider) -> None:
    out = provider.read("Inbox/hello.md")
    assert out.path == "Inbox/hello.md"
    assert out.content.strip() == "Body content here."
    assert out.frontmatter == {"title": "Hello"}
    assert out.size > 0


def test_read_missing_path_raises_not_found(provider: VaultProvider) -> None:
    with pytest.raises(NotFound):
        provider.read("does/not/exist.md")


def test_create_writes_new_file_with_frontmatter(provider: VaultProvider) -> None:
    out = provider.write(
        "Inbox/created.md",
        mode="create",
        content="freshly written\n",
        frontmatter_data={"created": "2026-04-29", "status": "active"},
    )
    assert out.op == "create"
    roundtrip = provider.read("Inbox/created.md")
    assert "freshly written" in roundtrip.content
    assert roundtrip.frontmatter == {"created": "2026-04-29", "status": "active"}


def test_create_on_existing_path_raises_conflict(provider: VaultProvider) -> None:
    provider.write("Inbox/dup.md", mode="create", content="x")
    with pytest.raises(Conflict):
        provider.write("Inbox/dup.md", mode="create", content="x")


def test_replace_requires_existing_file(provider: VaultProvider) -> None:
    with pytest.raises(NotFound):
        provider.write("Inbox/missing.md", mode="replace", content="x")


def test_replace_overwrites_existing_file(provider: VaultProvider) -> None:
    provider.write("Inbox/r.md", mode="create", content="original\n")
    provider.write(
        "Inbox/r.md",
        mode="replace",
        content="rewritten\n",
        frontmatter_data={"title": "R"},
    )
    out = provider.read("Inbox/r.md")
    assert "rewritten" in out.content
    assert "original" not in out.content
    assert out.frontmatter == {"title": "R"}


def test_append_creates_if_missing(provider: VaultProvider) -> None:
    out = provider.write("Inbox/a.md", mode="append", content="line one")
    assert out.op == "append"
    assert provider.read("Inbox/a.md").content.strip() == "line one"


def test_append_extends_existing_file(provider: VaultProvider) -> None:
    provider.write("Inbox/extend.md", mode="create", content="first\n")
    provider.write("Inbox/extend.md", mode="append", content="second\n")
    body = provider.read("Inbox/extend.md").content
    assert "first" in body
    assert "second" in body
    assert body.index("first") < body.index("second")


def test_path_traversal_via_dotdot_is_rejected(provider: VaultProvider) -> None:
    with pytest.raises(BadRequest):
        provider.read("../escape.md")


def test_absolute_path_is_rejected(provider: VaultProvider) -> None:
    with pytest.raises(BadRequest):
        provider.read("/etc/passwd")


def test_symlink_escape_is_rejected(provider: VaultProvider, tmp_path: Path) -> None:
    """A symlink within the vault that points outside must not unlock outside reads."""
    outside = tmp_path / "secret.md"
    outside.write_text("secret\n", encoding="utf-8")
    (provider.root / "Inbox" / "evil.md").symlink_to(outside)
    with pytest.raises(BadRequest):
        provider.read("Inbox/evil.md")


def test_empty_path_is_rejected(provider: VaultProvider) -> None:
    with pytest.raises(BadRequest):
        provider.read("")


def test_invalid_mode_is_rejected(provider: VaultProvider) -> None:
    with pytest.raises(BadRequest):
        provider.write("Inbox/x.md", mode="upsert", content="")  # type: ignore[arg-type]


def test_frontmatter_round_trip_preserves_field_order(provider: VaultProvider) -> None:
    """python-frontmatter is documented to preserve key order on dump."""
    metadata = {"created": "2026-04-29", "topic": "x", "status": "active", "z_last": 1}
    provider.write(
        "Inbox/order.md",
        mode="create",
        content="body\n",
        frontmatter_data=metadata,
    )
    raw = (provider.root / "Inbox" / "order.md").read_text(encoding="utf-8")
    indices = [raw.find(f"{k}:") for k in metadata]
    assert all(i > 0 for i in indices)
    assert indices == sorted(indices)


def test_provider_unconfigured_raises_dependency_unavailable() -> None:
    p = VaultProvider(None)
    assert p.configured is False
    from bridge.errors import DependencyUnavailable

    with pytest.raises(DependencyUnavailable):
        p.read("anything.md")
