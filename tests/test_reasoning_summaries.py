from __future__ import annotations

import unittest
from unittest.mock import patch

from coding_agents.team import _resolve_model_value


class ReasoningSummaryModelTests(unittest.TestCase):
    def test_openai_reasoning_effort_requests_responses_summary_blocks(self) -> None:
        with patch("coding_agents.team.init_chat_model", return_value="model") as init_chat_model:
            model = _resolve_model_value(model="openai:gpt-5.4", reasoning_effort="medium")

        self.assertEqual(model, "model")
        init_chat_model.assert_called_once_with(
            model="openai:gpt-5.4",
            reasoning={"effort": "medium", "summary": "auto"},
            use_responses_api=True,
            output_version="responses/v1",
        )

    def test_non_openai_reasoning_effort_keeps_provider_neutral_parameter(self) -> None:
        with patch("coding_agents.team.init_chat_model", return_value="model") as init_chat_model:
            model = _resolve_model_value(model="anthropic:claude-sonnet-4-5", reasoning_effort="high")

        self.assertEqual(model, "model")
        init_chat_model.assert_called_once_with(
            model="anthropic:claude-sonnet-4-5",
            reasoning_effort="high",
        )


if __name__ == "__main__":
    unittest.main()
