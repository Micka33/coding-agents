from __future__ import annotations

import unittest
from types import SimpleNamespace
from unittest.mock import patch

from src.team_instanciator.model_resolver import ModelResolver
from src.team_instanciator.runtime_configuration import RuntimeConfiguration
from src.team_instanciator.team_instanciator_error import TeamInstanciatorError


class ModelResolverTests(unittest.TestCase):
    def test_openai_reasoning_effort_none_uses_responses_api(self) -> None:
        team = self._team(model="openai:gpt-5.4-mini", reasoning_effort="medium")
        agent = SimpleNamespace(id="english-philosopher", model="openai:gpt-5.5", reasoning_effort="none")

        with (
            self.assertLogs("src.team_instanciator.model_resolver", level="WARNING") as logs,
            patch("src.team_instanciator.model_resolver.init_chat_model", return_value="model") as init_chat_model,
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

        with patch("src.team_instanciator.model_resolver.init_chat_model", return_value="model") as init_chat_model:
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

        with patch("src.team_instanciator.model_resolver.init_chat_model", return_value="model") as init_chat_model:
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

        with patch("src.team_instanciator.model_resolver.init_chat_model", return_value="model") as init_chat_model:
            resolved = ModelResolver(RuntimeConfiguration({"ANTHROPIC_API_KEY": "test-key"})).resolve(team, agent)

        self.assertEqual(resolved, "model")
        init_chat_model.assert_called_once_with(
            model="anthropic:claude-sonnet-4-5",
            api_key="test-key",
            reasoning_effort="high",
        )

    def test_without_kwargs_returns_model_name_directly(self) -> None:
        team = self._team(model="gpt-5.4-mini", reasoning_effort=None)
        agent = SimpleNamespace(id="speaker", model="inherit", reasoning_effort="inherit")

        resolved = ModelResolver(RuntimeConfiguration()).resolve(team, agent)

        self.assertEqual(resolved, "gpt-5.4-mini")

    def test_model_and_reasoning_effort_can_come_from_runtime_or_process_env(self) -> None:
        team = SimpleNamespace(
            defaults=SimpleNamespace(
                model=SimpleNamespace(env="MODEL_ENV", default=None),
                reasoning_effort=SimpleNamespace(env="REASONING_ENV", default=None),
            )
        )
        agent = SimpleNamespace(id="speaker", model="inherit", reasoning_effort="inherit")

        with patch("src.team_instanciator.model_resolver.init_chat_model", return_value="model") as init_chat_model:
            resolved = ModelResolver(
                RuntimeConfiguration(
                    {
                        "MODEL_ENV": "openai:gpt-runtime",
                        "REASONING_ENV": "low",
                        "OPENAI_API_KEY": "test-key",
                    }
                )
            ).resolve(team, agent)

        self.assertEqual(resolved, "model")
        init_chat_model.assert_called_once_with(
            model="openai:gpt-runtime",
            api_key="test-key",
            reasoning={"effort": "low", "summary": "auto"},
            use_responses_api=True,
            output_version="responses/v1",
        )

        with patch.dict("os.environ", {"MODEL_ENV": "gpt-process", "REASONING_ENV": ""}, clear=True):
            self.assertEqual(ModelResolver(RuntimeConfiguration()).resolve(team, agent), "gpt-process")

    def test_missing_inherited_model_raises(self) -> None:
        team = self._team(model=None, reasoning_effort=None)
        agent = SimpleNamespace(id="speaker", model="inherit", reasoning_effort="inherit")

        with self.assertRaisesRegex(TeamInstanciatorError, "Missing model"):
            ModelResolver(RuntimeConfiguration()).resolve(team, agent)

    def test_blank_reasoning_effort_is_ignored_and_openai_prefixes_are_detected(self) -> None:
        resolver = ModelResolver(RuntimeConfiguration())

        self.assertIsNone(resolver._normalize_reasoning_effort(None))
        self.assertIsNone(resolver._normalize_reasoning_effort("  "))
        self.assertTrue(resolver._is_openai_model("o3-mini"))

    def _team(self, *, model: str, reasoning_effort: str | None) -> SimpleNamespace:
        return SimpleNamespace(
            defaults=SimpleNamespace(
                model=SimpleNamespace(env=None, default=model),
                reasoning_effort=SimpleNamespace(env=None, default=reasoning_effort),
            )
        )


if __name__ == "__main__":
    unittest.main()
