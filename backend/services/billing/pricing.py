"""AI model rate card and cost estimation (Phase 1 cost tracking).

A static, operator-configured price table maps model names to USD rates per
1 million tokens. Costs are *estimates*: they use each provider's reported
token counts and configured rates, never a billing API.

Money is carried as US dollars (float) at the edges but accumulated in
MongoDB as **integer micro-dollars** (``estimated_cost_micros``, 1e-6 USD)
so atomic ``$inc`` rollups never drift through float addition.

Rates are configured via ``AI_MODEL_PRICING_JSON`` (a JSON object keyed by
model name). The built-in defaults reflect public list prices at time of
writing and can be overridden per model; a ``"*"`` entry prices any model
without an explicit row. Models with no applicable rate accrue zero cost
(and log a throttled warning) rather than a wrong number.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass

logger = logging.getLogger("webchat_ai")

MICROS_PER_DOLLAR = 1_000_000
WILDCARD_MODEL = "*"

DEFAULT_GEMINI_FLASH = "gemini-2.5-flash"


@dataclass(frozen=True)
class ModelPrice:
    """USD rates per 1 million tokens for one model."""

    input_per_million: float
    output_per_million: float
    embedding_per_million: float = 0.0


#: Built-in fallback rate card (public list prices, USD / 1M tokens).
DEFAULT_RATE_CARD: dict[str, ModelPrice] = {
    DEFAULT_GEMINI_FLASH: ModelPrice(
        input_per_million=0.30,
        output_per_million=2.50,
        embedding_per_million=0.075,
    ),
}


def load_rate_card(raw_json: str | None) -> dict[str, ModelPrice]:
    """Merge the operator's ``AI_MODEL_PRICING_JSON`` over the defaults.

    Raises ``ValueError`` on malformed JSON or non-numeric/negative rates so
    misconfiguration fails fast at service construction instead of silently
    producing zero-cost traffic.
    """
    card: dict[str, ModelPrice] = dict(DEFAULT_RATE_CARD)
    if not raw_json or not raw_json.strip():
        return card
    try:
        raw = json.loads(raw_json)
    except json.JSONDecodeError as exc:
        raise ValueError(f"AI_MODEL_PRICING_JSON is not valid JSON: {exc}") from exc
    if not isinstance(raw, dict):
        raise ValueError("AI_MODEL_PRICING_JSON must be a JSON object keyed by model name.")
    for model, rates in raw.items():
        if not isinstance(rates, dict):
            raise ValueError(f"Pricing for {model!r} must be an object of rates.")
        parsed: dict[str, float] = {}
        for key in ("input_per_million", "output_per_million", "embedding_per_million"):
            if key not in rates:
                continue
            value = rates[key]
            if not isinstance(value, (int, float)) or value < 0:
                raise ValueError(f"Rate {key!r} for {model!r} must be a non-negative number.")
            parsed[key] = float(value)
        base = card.get(model, ModelPrice(0.0, 0.0))
        card[model] = ModelPrice(
            input_per_million=parsed.get("input_per_million", base.input_per_million),
            output_per_million=parsed.get("output_per_million", base.output_per_million),
            embedding_per_million=parsed.get("embedding_per_million", base.embedding_per_million),
        )
    return card


def get_model_price(card: dict[str, ModelPrice], model_name: str) -> ModelPrice | None:
    """Rate row for *model_name*, falling back to the ``"*"`` wildcard."""
    return card.get(model_name) or card.get(WILDCARD_MODEL)


def estimate_generation_cost(
    price: ModelPrice,
    *,
    input_tokens: int,
    output_tokens: int,
) -> float:
    """``input*in_rate + output*out_rate`` (rates are USD per 1M tokens)."""
    cost = (
        input_tokens * price.input_per_million / MICROS_PER_DOLLAR
        + output_tokens * price.output_per_million / MICROS_PER_DOLLAR
    )
    # Rates are non-negative and token counts are ints, so cost cannot go
    # negative; clamp guards against pathological float noise anyway.
    return max(0.0, cost)


def estimate_embedding_cost(price: ModelPrice, *, tokens: int) -> float:
    """Cost for *tokens* embedded at the model's embedding rate."""
    return max(0.0, tokens * price.embedding_per_million / MICROS_PER_DOLLAR)


def dollars_to_micros(dollars: float) -> int:
    """Convert USD to integer micro-dollars (rounded to nearest)."""
    return int(round(dollars * MICROS_PER_DOLLAR))


def micros_to_dollars(micros: int) -> float:
    """Convert integer micro-dollars back to USD."""
    return micros / MICROS_PER_DOLLAR


__all__ = [
    "DEFAULT_GEMINI_FLASH",
    "DEFAULT_RATE_CARD",
    "MICROS_PER_DOLLAR",
    "ModelPrice",
    "WILDCARD_MODEL",
    "dollars_to_micros",
    "estimate_embedding_cost",
    "estimate_generation_cost",
    "get_model_price",
    "load_rate_card",
    "micros_to_dollars",
]
