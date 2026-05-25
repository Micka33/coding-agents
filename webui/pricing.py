from __future__ import annotations

import json
import re
from decimal import Decimal
from pathlib import Path
from typing import Any


DEFAULT_PRICING_PATH = (
    Path(__file__).resolve().parent
    / "pricing"
    / "openai_text_token_pricing.v2026-05-26.json"
)
_MODEL_DATE_SUFFIX = re.compile(r"^(?P<base>.+)-\d{4}-\d{2}-\d{2}$")
_TOKEN_UNIT = Decimal("1000000")


class PricingError(ValueError):
    """Raised when pricing data cannot be used for an estimate."""


class PricingNotFoundError(PricingError):
    """Raised when no pricing row matches a model/tier pair."""


def load_pricing_catalog(path: Path | str = DEFAULT_PRICING_PATH) -> dict[str, Any]:
    """Load the versioned pricing catalog."""

    with Path(path).open(encoding="utf-8") as handle:
        return json.load(handle)


def resolve_model_pricing(
    model: str,
    *,
    tier: str = "standard",
    catalog: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Return the pricing row matching a model name and service tier.

    Exact model IDs win. If no exact row exists, dated model IDs such as
    ``gpt-5.5-2026-04-23`` fall back to their base model, ``gpt-5.5``.
    """

    catalog = catalog or load_pricing_catalog()
    tier_data = catalog.get("tiers", {}).get(tier)
    if not tier_data:
        raise PricingNotFoundError(f"No pricing tier found for {tier!r}")

    for candidate in _model_candidates(model):
        for group in ("text_models", "specialized_text_models"):
            row = tier_data.get(group, {}).get(candidate)
            if row is not None:
                return {
                    "pricing_version": catalog["pricing_version"],
                    "currency": catalog["currency"],
                    "tier": tier,
                    "requested_model": model,
                    "priced_model": candidate,
                    "pricing_group": group,
                    "pricing": row,
                }

    raise PricingNotFoundError(f"No pricing row found for model {model!r} in tier {tier!r}")


def estimate_text_token_cost(
    usage: dict[str, Any],
    model: str,
    *,
    tier: str = "standard",
    regional_processing: bool = False,
    catalog: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Estimate text-token cost from persisted LangChain/OpenAI usage metadata."""

    catalog = catalog or load_pricing_catalog()
    resolved = resolve_model_pricing(model, tier=tier, catalog=catalog)
    pricing = resolved["pricing"]

    input_tokens = _token_count(usage, "input_tokens")
    output_tokens = _token_count(usage, "output_tokens")
    cached_input_tokens = min(_cached_input_tokens(usage), input_tokens)
    uncached_input_tokens = input_tokens - cached_input_tokens

    input_rate = _rate(pricing, "input_usd_per_1m")
    cached_input_rate = _rate(pricing, "cached_input_usd_per_1m")
    output_rate = _rate(pricing, "output_usd_per_1m")
    if output_tokens and output_rate is None:
        raise PricingError(f"Output token pricing is not available for {resolved['priced_model']!r}")

    multiplier = _regional_multiplier(catalog, resolved["priced_model"]) if regional_processing else Decimal("1")
    effective_cached_input_rate = cached_input_rate if cached_input_rate is not None else input_rate
    input_cost = (Decimal(uncached_input_tokens) / _TOKEN_UNIT) * input_rate * multiplier
    cached_input_cost = (Decimal(cached_input_tokens) / _TOKEN_UNIT) * effective_cached_input_rate * multiplier
    output_cost = (Decimal(output_tokens) / _TOKEN_UNIT) * (output_rate or Decimal("0")) * multiplier
    total = input_cost + cached_input_cost + output_cost

    return {
        "pricing_version": resolved["pricing_version"],
        "currency": resolved["currency"],
        "tier": resolved["tier"],
        "requested_model": resolved["requested_model"],
        "priced_model": resolved["priced_model"],
        "regional_processing": regional_processing,
        "regional_multiplier": float(multiplier),
        "tokens": {
            "input": input_tokens,
            "input_uncached": uncached_input_tokens,
            "input_cached": cached_input_tokens,
            "output": output_tokens,
            "reasoning_output": _reasoning_output_tokens(usage),
        },
        "rates_usd_per_1m": {
            "input": float(input_rate),
            "cached_input": float(cached_input_rate) if cached_input_rate is not None else None,
            "output": float(output_rate) if output_rate is not None else None,
        },
        "subtotals_usd": {
            "input": _decimal_text(input_cost),
            "cached_input": _decimal_text(cached_input_cost),
            "output": _decimal_text(output_cost),
        },
        "estimated_cost_usd": float(total),
        "estimated_cost_usd_decimal": _decimal_text(total),
    }


def _model_candidates(model: str) -> list[str]:
    normalized = str(model).strip()
    candidates = [normalized]
    match = _MODEL_DATE_SUFFIX.match(normalized)
    if match:
        candidates.append(match.group("base"))
    return candidates


def _token_count(usage: dict[str, Any], key: str) -> int:
    value = usage.get(key) or 0
    return max(int(value), 0)


def _cached_input_tokens(usage: dict[str, Any]) -> int:
    details = usage.get("input_token_details") or {}
    return max(int(details.get("cache_read") or details.get("cached_tokens") or 0), 0)


def _reasoning_output_tokens(usage: dict[str, Any]) -> int:
    details = usage.get("output_token_details") or {}
    return max(int(details.get("reasoning") or 0), 0)


def _rate(pricing: dict[str, Any], key: str) -> Decimal | None:
    value = pricing.get(key)
    if value is None:
        return None
    return Decimal(str(value))


def _regional_multiplier(catalog: dict[str, Any], priced_model: str) -> Decimal:
    uplift = catalog.get("regional_processing_uplift") or {}
    models = set(uplift.get("models") or [])
    if priced_model in models:
        return Decimal(str(uplift.get("uplift_multiplier") or 1))
    return Decimal("1")


def _decimal_text(value: Decimal) -> str:
    return format(value.normalize(), "f")
