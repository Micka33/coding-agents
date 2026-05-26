from __future__ import annotations

import unittest

from webui.pricing import (
    combine_cost_summaries,
    estimate_messages_cost,
    estimate_text_token_cost,
    load_pricing_catalog,
    resolve_model_pricing,
)


class WebUiPricingTests(unittest.TestCase):
    def test_loads_versioned_pricing_catalog(self) -> None:
        catalog = load_pricing_catalog()

        self.assertEqual(catalog["schema_version"], 1)
        self.assertEqual(
            catalog["pricing_version"],
            "openai-text-token-pricing-2026-05-26-user-provided",
        )
        self.assertEqual(
            catalog["tiers"]["standard"]["text_models"]["gpt-5.5"]["output_usd_per_1m"],
            30,
        )

    def test_resolves_dated_model_to_base_pricing(self) -> None:
        resolved = resolve_model_pricing("gpt-5.5-2026-04-23")

        self.assertEqual(resolved["priced_model"], "gpt-5.5")
        self.assertEqual(resolved["pricing"]["input_usd_per_1m"], 5)

    def test_exact_dated_model_pricing_wins_over_base_fallback(self) -> None:
        resolved = resolve_model_pricing("gpt-4o-2024-05-13")

        self.assertEqual(resolved["priced_model"], "gpt-4o-2024-05-13")
        self.assertEqual(resolved["pricing"]["input_usd_per_1m"], 5)

    def test_estimates_cost_with_cached_input_tokens(self) -> None:
        estimate = estimate_text_token_cost(
            {
                "input_tokens": 1000,
                "output_tokens": 200,
                "total_tokens": 1200,
                "input_token_details": {"cache_read": 400},
                "output_token_details": {"reasoning": 100},
            },
            "gpt-5.5-2026-04-23",
        )

        self.assertEqual(estimate["priced_model"], "gpt-5.5")
        self.assertEqual(
            estimate["tokens"],
            {
                "input": 1000,
                "input_uncached": 600,
                "input_cached": 400,
                "output": 200,
                "reasoning_output": 100,
            },
        )
        self.assertEqual(estimate["subtotals_usd"]["input"], "0.003")
        self.assertEqual(estimate["subtotals_usd"]["cached_input"], "0.0002")
        self.assertEqual(estimate["subtotals_usd"]["output"], "0.006")
        self.assertEqual(estimate["estimated_cost_usd_decimal"], "0.0092")

    def test_estimates_normalized_message_collection_cost(self) -> None:
        summary = estimate_messages_cost(
            [
                {
                    "usage": {
                        "input_tokens": 1000,
                        "output_tokens": 100,
                        "input_token_details": {"cache_read": 500},
                    },
                    "responseMetadata": {"model_name": "gpt-5.5-2026-04-23"},
                    "timestamp": {"iso": "2026-05-25T21:15:00Z", "epochMs": 1779743700000},
                },
                {"usage": None, "responseMetadata": {}},
            ],
        )

        self.assertEqual(summary["calls_with_usage"], 1)
        self.assertEqual(summary["messages_without_usage"], 1)
        self.assertFalse(summary["partial"])
        self.assertEqual(summary["estimated_cost_usd_decimal"], "0.00575")
        self.assertEqual(summary["by_model"][0]["priced_model"], "gpt-5.5")
        self.assertEqual(summary["time_series"]["hour"][0]["bucket"], "2026-05-25T21:00:00Z")
        self.assertEqual(summary["time_series"]["day"][0]["bucket"], "2026-05-25")
        self.assertEqual(summary["time_series"]["week"][0]["bucket"], "2026-W22")
        self.assertEqual(summary["time_series"]["hour"][0]["estimated_cost_usd_decimal"], "0.00575")

    def test_unknown_model_keeps_partial_token_counts(self) -> None:
        summary = estimate_messages_cost(
            [
                {
                    "usage": {"input_tokens": 1000, "output_tokens": 100},
                    "responseMetadata": {"model_name": "unknown-model"},
                }
            ],
        )

        self.assertTrue(summary["partial"])
        self.assertEqual(summary["unpriced_calls"], 1)
        self.assertEqual(summary["tokens"]["input"], 1000)
        self.assertEqual(summary["estimated_cost_usd_decimal"], "0")

    def test_combines_cost_summaries(self) -> None:
        first = estimate_messages_cost(
            [
                {
                    "usage": {"input_tokens": 1000, "output_tokens": 100},
                    "responseMetadata": {"model_name": "gpt-5.5-2026-04-23"},
                    "timestamp": {"iso": "2026-05-25T21:15:00Z", "epochMs": 1779743700000},
                }
            ],
        )
        second = estimate_messages_cost(
            [
                {
                    "usage": {"input_tokens": 1000, "output_tokens": 100},
                    "responseMetadata": {"model_name": "gpt-5.5-2026-04-23"},
                    "timestamp": {"iso": "2026-05-25T22:15:00Z", "epochMs": 1779747300000},
                }
            ],
        )

        combined = combine_cost_summaries([first, second])

        self.assertEqual(combined["calls_with_usage"], 2)
        self.assertEqual(combined["by_model"][0]["calls"], 2)
        self.assertEqual(combined["estimated_cost_usd_decimal"], "0.016")
        self.assertEqual(len(combined["time_series"]["hour"]), 2)
        self.assertEqual(len(combined["time_series"]["day"]), 1)
        self.assertEqual(combined["time_series"]["day"][0]["calls"], 2)


if __name__ == "__main__":
    unittest.main()
