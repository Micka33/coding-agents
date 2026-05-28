from __future__ import annotations

import unittest
from types import SimpleNamespace
from unittest.mock import patch

from coding_agents.team_instanciator.model_resolver import ModelResolver
from coding_agents.team_instanciator.runtime_configuration import RuntimeConfiguration


class ModelResolverTests(unittest.TestCase):
    def test_openai_reasoning_effort_none_uses_responses_api(self) -> None:
        team = self._team(model="openai:gpt-5.4-mini", reasoning_effort="medium")
        agent = SimpleNamespace(id="english-philosopher", model="openai:gpt-5.5", reasoning_effort="none")

        with (
            self.assertLogs("coding_agents.team_instanciator.model_resolver", level="WARNING") as logs,
            patch("coding_agents.team_instanciator.model_resolver.init_chat_model", return_value="model") as init_chat_model,
        ):
            resolved = ModelResolver(RuntimeConfiguration({"OPENAI_API_KEY": "test-key"})).resolve(team, agent)

        self.assertEqual(resolved, "model")
        init_chat_model.assert_called_once_with(
            model="openai:gpt-5.5",
            api_key="test-key",
            reasoning={"effort": "none"},
            use_responses_api=True,
            output_version="responses/v1",
        )
        self.assertIn("raw_reasoning_effort='none'", logs.output[0])
        self.assertIn("effective_reasoning_effort='none'", logs.output[0])
        self.assertIn("'api_key': '<redacted>'", logs.output[0])

    def test_inherited_openai_reasoning_effort_none_uses_responses_api(self) -> None:
        team = self._team(model="openai:gpt-5.4-mini", reasoning_effort="none")
        agent = SimpleNamespace(id="german-philosopher", model="inherit", reasoning_effort="inherit")

        with patch("coding_agents.team_instanciator.model_resolver.init_chat_model", return_value="model") as init_chat_model:
            resolved = ModelResolver(RuntimeConfiguration({"OPENAI_API_KEY": "test-key"})).resolve(team, agent)

        self.assertEqual(resolved, "model")
        init_chat_model.assert_called_once_with(
            model="openai:gpt-5.4-mini",
            api_key="test-key",
            reasoning={"effort": "none"},
            use_responses_api=True,
            output_version="responses/v1",
        )

    def test_openai_non_none_reasoning_effort_requests_summary(self) -> None:
        team = self._team(model="openai:gpt-5.4-mini", reasoning_effort="high")
        agent = SimpleNamespace(id="speaker", model="inherit", reasoning_effort="inherit")

        with patch("coding_agents.team_instanciator.model_resolver.init_chat_model", return_value="model") as init_chat_model:
            resolved = ModelResolver(RuntimeConfiguration({"OPENAI_API_KEY": "test-key"})).resolve(team, agent)

        self.assertEqual(resolved, "model")
        init_chat_model.assert_called_once_with(
            model="openai:gpt-5.4-mini",
            api_key="test-key",
            reasoning={"effort": "high", "summary": "auto"},
            use_responses_api=True,
            output_version="responses/v1",
        )

    def test_non_none_reasoning_effort_is_sent(self) -> None:
        team = self._team(model="anthropic:claude-sonnet-4-5", reasoning_effort="high")
        agent = SimpleNamespace(id="speaker", model="inherit", reasoning_effort="inherit")

        with patch("coding_agents.team_instanciator.model_resolver.init_chat_model", return_value="model") as init_chat_model:
            resolved = ModelResolver(RuntimeConfiguration({"ANTHROPIC_API_KEY": "test-key"})).resolve(team, agent)

        self.assertEqual(resolved, "model")
        init_chat_model.assert_called_once_with(
            model="anthropic:claude-sonnet-4-5",
            api_key="test-key",
            reasoning_effort="high",
        )

    def _team(self, *, model: str, reasoning_effort: str | None) -> SimpleNamespace:
        return SimpleNamespace(
            defaults=SimpleNamespace(
                model=SimpleNamespace(env=None, default=model),
                reasoning_effort=SimpleNamespace(env=None, default=reasoning_effort),
            )
        )


if __name__ == "__main__":
    unittest.main()
