"""OpenRouter pricing table for cost_usd computation at write time.

Hardcoded per `docs/telemetry-plan.md`. Refresh policy: this is updated
manually when OpenRouter changes pricing. Live querying (`/api/v1/models`
returns prices) was rejected for v1 because:

- It adds an extra HTTP call to the hot path.
- It introduces a non-deterministic cost field for replayed unit tests.
- The pricing tier rarely changes within a quarter.

The cost_usd field in telemetry is therefore a snapshot of the price-table
in effect at *recording time*. Backfills are out of scope; if a model's
price changes, historical rows keep their original costs.

Source: <https://openrouter.ai/models> as of 2026-04. Prices are USD per 1M
tokens, separate for prompt and completion. Models we expect to use:

- claude-haiku-4.5 — cheap classification / triage default
- claude-sonnet-4.5 — reasoning / drafting default
- claude-opus-4.7 — heavy reasoning, opt-in via model_hint

Add new entries when a brain or task starts using a new model. An
unrecognised model returns `(0.0, 0.0)` and the call still succeeds — the
telemetry row records cost_usd=0.0 with a `pricing_unknown` flag, which
the analyse-telemetry script flags for follow-up.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Final


@dataclass(frozen=True)
class ModelPrice:
    """USD per 1M tokens for prompt and completion respectively."""

    prompt: float
    completion: float


_PRICES: Final[dict[str, ModelPrice]] = {
    # Anthropic via OpenRouter — primary targets. Both the friendly id we
    # request AND the dated id OpenRouter echoes back in the response are
    # listed because cost_usd is computed from the response's `model` field.
    # Seen during Session 3 manual verification: requesting
    # `anthropic/claude-haiku-4.5` returned `anthropic/claude-4.5-haiku-20251001`.
    "anthropic/claude-haiku-4.5": ModelPrice(prompt=1.00, completion=5.00),
    "anthropic/claude-4.5-haiku-20251001": ModelPrice(prompt=1.00, completion=5.00),
    "anthropic/claude-sonnet-4.5": ModelPrice(prompt=3.00, completion=15.00),
    "anthropic/claude-4.5-sonnet-20251001": ModelPrice(prompt=3.00, completion=15.00),
    "anthropic/claude-opus-4.7": ModelPrice(prompt=15.00, completion=75.00),
    "anthropic/claude-4.7-opus-20251101": ModelPrice(prompt=15.00, completion=75.00),
    # Backstops for routing failures / experiments.
    "openai/gpt-4o-mini": ModelPrice(prompt=0.15, completion=0.60),
    "openai/gpt-4o": ModelPrice(prompt=2.50, completion=10.00),
    "meta-llama/llama-3.3-70b-instruct": ModelPrice(prompt=0.70, completion=0.85),
}


def lookup(model: str) -> ModelPrice | None:
    """Return the price for `model`, or None if unknown."""
    return _PRICES.get(model)


def compute_cost_usd(model: str, prompt_tokens: int, completion_tokens: int) -> float:
    """Return cost in USD (rounded to 6 decimal places). Unknown model → 0.0."""
    price = _PRICES.get(model)
    if price is None:
        return 0.0
    cost = (prompt_tokens * price.prompt + completion_tokens * price.completion) / 1_000_000
    return round(cost, 6)


def known_models() -> list[str]:
    return sorted(_PRICES.keys())
