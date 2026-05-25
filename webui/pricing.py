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


def estimate_messages_cost(
    messages: list[dict[str, Any]],
    *,
    tier: str = "standard",
    regional_processing: bool = False,
    catalog: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Aggregate token costs for normalized Web UI messages."""

    catalog = catalog or load_pricing_catalog()
    totals = _empty_cost_summary(catalog, tier)
    by_model: dict[str, dict[str, Any]] = {}
    unpriced_models: dict[str, dict[str, Any]] = {}

    for message in messages:
        usage = message.get("usage")
        if not usage:
            totals["messages_without_usage"] += 1
            continue

        totals["calls_with_usage"] += 1
        model = _message_model(message)
        if not model:
            totals["unpriced_calls"] += 1
            _add_unpriced(unpriced_models, "unknown", "Message has usage metadata but no model metadata.")
            _add_raw_usage_tokens(totals, usage)
            continue

        try:
            estimate = estimate_text_token_cost(
                usage,
                model,
                tier=tier,
                regional_processing=regional_processing,
                catalog=catalog,
            )
        except PricingError as exc:
            totals["unpriced_calls"] += 1
            _add_unpriced(unpriced_models, model, str(exc))
            _add_raw_usage_tokens(totals, usage)
            continue

        _merge_estimate(totals, estimate)
        model_key = estimate["priced_model"]
        if model_key not in by_model:
            by_model[model_key] = _empty_model_summary(estimate)
        _merge_estimate(by_model[model_key], estimate)

    return _finalize_cost_summary(totals, by_model, unpriced_models)


def combine_cost_summaries(
    summaries: list[dict[str, Any]],
    *,
    pricing_version: str | None = None,
    currency: str = "USD",
    tier: str = "standard",
) -> dict[str, Any]:
    """Combine already-computed cost summaries without re-reading messages."""

    totals = {
        "pricing_version": pricing_version,
        "currency": currency,
        "tier": tier,
        "estimated_cost_usd": Decimal("0"),
        "tokens": _empty_token_counts(),
        "subtotals_usd": _empty_cost_parts(),
        "calls_with_usage": 0,
        "messages_without_usage": 0,
        "unpriced_calls": 0,
    }
    by_model: dict[str, dict[str, Any]] = {}
    unpriced_models: dict[str, dict[str, Any]] = {}

    for summary in summaries:
        if not summary:
            continue
        if summary.get("pricing_version"):
            totals["pricing_version"] = summary["pricing_version"]
        totals["calls_with_usage"] += int(summary.get("calls_with_usage") or 0)
        totals["messages_without_usage"] += int(summary.get("messages_without_usage") or 0)
        totals["unpriced_calls"] += int(summary.get("unpriced_calls") or 0)
        totals["estimated_cost_usd"] += Decimal(str(summary.get("estimated_cost_usd_decimal") or 0))
        _merge_token_counts(totals["tokens"], summary.get("tokens") or {})
        _merge_cost_parts(totals["subtotals_usd"], summary.get("subtotals_usd") or {})

        for model_summary in summary.get("by_model") or []:
            model_key = model_summary.get("priced_model") or model_summary.get("model") or "unknown"
            if model_key not in by_model:
                by_model[model_key] = _empty_model_summary_from_summary(model_summary, currency, tier)
            _merge_cost_summary_dict(by_model[model_key], model_summary)

        for unpriced in summary.get("unpriced_models") or []:
            _add_unpriced(
                unpriced_models,
                str(unpriced.get("model") or "unknown"),
                str(unpriced.get("error") or "No pricing row found."),
                calls=int(unpriced.get("calls") or 0),
            )

    return _finalize_cost_summary(totals, by_model, unpriced_models)


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


def _message_model(message: dict[str, Any]) -> str | None:
    metadata = message.get("responseMetadata") or {}
    if not isinstance(metadata, dict):
        return None
    value = metadata.get("model_name") or metadata.get("model") or metadata.get("modelName")
    return str(value) if value else None


def _empty_cost_summary(catalog: dict[str, Any], tier: str) -> dict[str, Any]:
    return {
        "pricing_version": catalog["pricing_version"],
        "currency": catalog["currency"],
        "tier": tier,
        "estimated_cost_usd": Decimal("0"),
        "tokens": _empty_token_counts(),
        "subtotals_usd": _empty_cost_parts(),
        "calls_with_usage": 0,
        "messages_without_usage": 0,
        "unpriced_calls": 0,
    }


def _empty_model_summary(estimate: dict[str, Any]) -> dict[str, Any]:
    return {
        "model": estimate["requested_model"],
        "priced_model": estimate["priced_model"],
        "currency": estimate["currency"],
        "tier": estimate["tier"],
        "rates_usd_per_1m": estimate["rates_usd_per_1m"],
        "estimated_cost_usd": Decimal("0"),
        "tokens": _empty_token_counts(),
        "subtotals_usd": _empty_cost_parts(),
        "calls": 0,
    }


def _empty_model_summary_from_summary(
    summary: dict[str, Any],
    currency: str,
    tier: str,
) -> dict[str, Any]:
    return {
        "model": summary.get("model") or summary.get("priced_model") or "unknown",
        "priced_model": summary.get("priced_model") or summary.get("model") or "unknown",
        "currency": summary.get("currency") or currency,
        "tier": summary.get("tier") or tier,
        "rates_usd_per_1m": summary.get("rates_usd_per_1m") or {},
        "estimated_cost_usd": Decimal("0"),
        "tokens": _empty_token_counts(),
        "subtotals_usd": _empty_cost_parts(),
        "calls": 0,
    }


def _empty_token_counts() -> dict[str, int]:
    return {
        "input": 0,
        "input_uncached": 0,
        "input_cached": 0,
        "output": 0,
        "reasoning_output": 0,
    }


def _empty_cost_parts() -> dict[str, Decimal]:
    return {
        "input": Decimal("0"),
        "cached_input": Decimal("0"),
        "output": Decimal("0"),
    }


def _merge_estimate(target: dict[str, Any], estimate: dict[str, Any]) -> None:
    target["estimated_cost_usd"] += Decimal(str(estimate["estimated_cost_usd_decimal"]))
    _merge_token_counts(target["tokens"], estimate["tokens"])
    _merge_cost_parts(target["subtotals_usd"], estimate["subtotals_usd"])
    if "calls" in target:
        target["calls"] += 1


def _merge_cost_summary_dict(target: dict[str, Any], source: dict[str, Any]) -> None:
    target["calls"] += int(source.get("calls") or source.get("calls_with_usage") or 0)
    target["estimated_cost_usd"] += Decimal(str(source.get("estimated_cost_usd_decimal") or 0))
    _merge_token_counts(target["tokens"], source.get("tokens") or {})
    _merge_cost_parts(target["subtotals_usd"], source.get("subtotals_usd") or {})


def _merge_token_counts(target: dict[str, int], source: dict[str, Any]) -> None:
    for key in _empty_token_counts():
        target[key] += int(source.get(key) or 0)


def _merge_cost_parts(target: dict[str, Decimal], source: dict[str, Any]) -> None:
    for key in _empty_cost_parts():
        target[key] += Decimal(str(source.get(key) or 0))


def _add_raw_usage_tokens(target: dict[str, Any], usage: dict[str, Any]) -> None:
    input_tokens = _token_count(usage, "input_tokens")
    cached_tokens = min(_cached_input_tokens(usage), input_tokens)
    target["tokens"]["input"] += input_tokens
    target["tokens"]["input_cached"] += cached_tokens
    target["tokens"]["input_uncached"] += input_tokens - cached_tokens
    target["tokens"]["output"] += _token_count(usage, "output_tokens")
    target["tokens"]["reasoning_output"] += _reasoning_output_tokens(usage)


def _add_unpriced(
    unpriced_models: dict[str, dict[str, Any]],
    model: str,
    error: str,
    *,
    calls: int = 1,
) -> None:
    if model not in unpriced_models:
        unpriced_models[model] = {"model": model, "calls": 0, "error": error}
    unpriced_models[model]["calls"] += calls


def _finalize_cost_summary(
    summary: dict[str, Any],
    by_model: dict[str, dict[str, Any]],
    unpriced_models: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    total = summary["estimated_cost_usd"]
    calls_with_usage = int(summary["calls_with_usage"])
    unpriced_calls = int(summary["unpriced_calls"])
    return {
        "pricing_version": summary.get("pricing_version"),
        "currency": summary.get("currency") or "USD",
        "tier": summary.get("tier") or "standard",
        "estimated_cost_usd": float(total),
        "estimated_cost_usd_decimal": _decimal_text(total),
        "partial": unpriced_calls > 0,
        "calls_with_usage": calls_with_usage,
        "messages_without_usage": int(summary["messages_without_usage"]),
        "priced_calls": calls_with_usage - unpriced_calls,
        "unpriced_calls": unpriced_calls,
        "tokens": summary["tokens"],
        "subtotals_usd": {
            key: _decimal_text(value)
            for key, value in summary["subtotals_usd"].items()
        },
        "by_model": [
            _finalize_model_summary(model_summary)
            for model_summary in sorted(
                by_model.values(),
                key=lambda item: item["estimated_cost_usd"],
                reverse=True,
            )
        ],
        "unpriced_models": sorted(
            unpriced_models.values(),
            key=lambda item: (-int(item.get("calls") or 0), str(item.get("model") or "")),
        ),
    }


def _finalize_model_summary(summary: dict[str, Any]) -> dict[str, Any]:
    total = summary["estimated_cost_usd"]
    return {
        "model": summary["model"],
        "priced_model": summary["priced_model"],
        "currency": summary["currency"],
        "tier": summary["tier"],
        "rates_usd_per_1m": summary.get("rates_usd_per_1m") or {},
        "calls": int(summary["calls"]),
        "tokens": summary["tokens"],
        "subtotals_usd": {
            key: _decimal_text(value)
            for key, value in summary["subtotals_usd"].items()
        },
        "estimated_cost_usd": float(total),
        "estimated_cost_usd_decimal": _decimal_text(total),
    }
