"""Pricing table: known model → exact USD; unknown model → 0.0."""

from __future__ import annotations

from bridge.providers.llm.pricing import compute_cost_usd, lookup


def test_known_model_returns_price() -> None:
    p = lookup("anthropic/claude-haiku-4.5")
    assert p is not None
    assert p.prompt == 1.00
    assert p.completion == 5.00


def test_unknown_model_returns_none() -> None:
    assert lookup("foo/bar-9000") is None


def test_compute_cost_usd_known_model() -> None:
    # 1000 prompt + 500 completion at haiku rates
    # = 1000 * 1.00 / 1e6 + 500 * 5.00 / 1e6 = 0.001 + 0.0025 = 0.0035
    assert compute_cost_usd("anthropic/claude-haiku-4.5", 1000, 500) == 0.0035


def test_compute_cost_usd_unknown_model_zero() -> None:
    assert compute_cost_usd("foo/bar-9000", 1000, 500) == 0.0


def test_compute_cost_usd_zero_tokens() -> None:
    assert compute_cost_usd("anthropic/claude-sonnet-4.5", 0, 0) == 0.0
