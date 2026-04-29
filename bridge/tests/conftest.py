"""Shared fixtures for the bridge test suite.

Each test gets a fresh FastAPI app pointed at a tempfile-backed token store,
so token shape can be tailored per test without process-wide state.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path

import pytest
from bridge.config import Settings
from bridge.main import create_app
from fastapi import FastAPI
from fastapi.testclient import TestClient


@dataclass(frozen=True)
class TokenFixture:
    plain: str
    actor: str
    scopes: tuple[str, ...]


def _digest(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


@pytest.fixture
def tokens(tmp_path: Path) -> tuple[Path, list[TokenFixture]]:
    """Write a tokens.dev.json file with a couple of canned identities."""
    fixtures = [
        TokenFixture(plain="dev-token-clu", actor="brain.clu", scopes=("llm:call", "vault:read")),
        TokenFixture(plain="dev-token-empty", actor="cli.test", scopes=()),
    ]
    body: dict[str, dict[str, object]] = {
        _digest(f.plain): {"actor": f.actor, "scopes": list(f.scopes)} for f in fixtures
    }
    path = tmp_path / "tokens.dev.json"
    path.write_text(json.dumps(body), encoding="utf-8")
    return path, fixtures


@pytest.fixture
def settings(tokens: tuple[Path, list[TokenFixture]]) -> Settings:
    path, _ = tokens
    return Settings(
        host="127.0.0.1",
        port=8788,
        log_level="info",
        token_store_path=path,
    )


@pytest.fixture
def app(settings: Settings) -> FastAPI:
    return create_app(settings)


@pytest.fixture
def client(app: FastAPI) -> Iterator[TestClient]:
    with TestClient(app) as c:
        yield c
