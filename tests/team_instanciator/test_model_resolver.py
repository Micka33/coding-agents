from __future__ import annotations

import unittest
from types import SimpleNamespace
from unittest.mock import patch

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage
from langchain_core.outputs import ChatGeneration, ChatResult

from src.team_instanciator.resolvers.model_resolver import ModelResolver
from src.team_instanciator.resolvers.model_reliability import (
    ModelReliabilityPolicy,
    ReliableChatModel,
    wrap_model_for_reliability,
)
from src.team_instanciator.configuration.runtime_configuration import RuntimeConfiguration
from src.team_instanciator.errors.team_instanciator_error import TeamInstanciatorError


class RecordingRunnable:
    def __init__(self) -> None:
        self.config_kwargs = None
        self.retry_kwargs = None

    def with_config(self, **kwargs):
        self.config_kwargs = kwargs
        return self

    def with_retry(self, **kwargs):
        self.retry_kwargs = kwargs
        return self


class RecordingChatModel(BaseChatModel):
    def __init__(self) -> None:
        super().__init__()
        object.__setattr__(self, "bound", RecordingRunnable())

    @property
    def _llm_type(self) -> str:
        return "recording"

    def _generate(self, messages, stop=None, run_manager=None, **kwargs):
        return ChatResult(generations=[ChatGeneration(message=AIMessage(content="ok"))])

    def bind(self, **kwargs):
        return self.bound

    def bind_tools(self, tools, *, tool_choice=None, **kwargs):
        return self.bound


class ModelResolverTests(unittest.TestCase):
    def test_openai_reasoning_effort_none_uses_responses_api(self) -> None:
        team = self._team(model="openai:gpt-5.4-mini", reasoning_effort="medium")
        agent = SimpleNamespace(id="english-philosopher", model="openai:gpt-5.5", reasoning_effort="none")

        with (
            self.assertLogs("src.team_instanciator.resolvers.model_resolver", level="WARNING") as logs,
            patch("src.team_instanciator.resolvers.model_resolver.init_chat_model", return_value="model") as init_chat_model,
        ):
            resolved = ModelResolver(RuntimeConfiguration({"OPENAI_API_KEY": "test-key"})).resolve(team, agent)

        self.assertEqual(resolved, "model")
        init_chat_model.assert_called_once_with(
            model="openai:gpt-5.5",
            api_key="test-key",
            streaming=True,
            stream_chunk_timeout=120.0,
            max_retries=0,
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

        with patch("src.team_instanciator.resolvers.model_resolver.init_chat_model", return_value="model") as init_chat_model:
            resolved = ModelResolver(RuntimeConfiguration({"OPENAI_API_KEY": "test-key"})).resolve(team, agent)

        self.assertEqual(resolved, "model")
        init_chat_model.assert_called_once_with(
            model="openai:gpt-5.4-mini",
            api_key="test-key",
            streaming=True,
            stream_chunk_timeout=120.0,
            max_retries=0,
            reasoning={"effort": "none"},
            use_responses_api=True,
            output_version="responses/v1",
        )

    def test_openai_non_none_reasoning_effort_requests_summary(self) -> None:
        team = self._team(model="openai:gpt-5.4-mini", reasoning_effort="high")
        agent = SimpleNamespace(id="speaker", model="inherit", reasoning_effort="inherit")

        with patch("src.team_instanciator.resolvers.model_resolver.init_chat_model", return_value="model") as init_chat_model:
            resolved = ModelResolver(RuntimeConfiguration({"OPENAI_API_KEY": "test-key"})).resolve(team, agent)

        self.assertEqual(resolved, "model")
        init_chat_model.assert_called_once_with(
            model="openai:gpt-5.4-mini",
            api_key="test-key",
            streaming=True,
            stream_chunk_timeout=120.0,
            max_retries=0,
            reasoning={"effort": "high", "summary": "auto"},
            use_responses_api=True,
            output_version="responses/v1",
        )

    def test_non_none_reasoning_effort_is_sent(self) -> None:
        team = self._team(model="anthropic:claude-sonnet-4-5", reasoning_effort="high")
        agent = SimpleNamespace(id="speaker", model="inherit", reasoning_effort="inherit")

        with patch("src.team_instanciator.resolvers.model_resolver.init_chat_model", return_value="model") as init_chat_model:
            resolved = ModelResolver(RuntimeConfiguration({"ANTHROPIC_API_KEY": "test-key"})).resolve(team, agent)

        self.assertEqual(resolved, "model")
        init_chat_model.assert_called_once_with(
            model="anthropic:claude-sonnet-4-5",
            api_key="test-key",
            timeout=120.0,
            max_retries=0,
            reasoning_effort="high",
        )

    def test_without_kwargs_still_initializes_model_for_reliability(self) -> None:
        team = self._team(model="gpt-5.4-mini", reasoning_effort=None)
        agent = SimpleNamespace(id="speaker", model="inherit", reasoning_effort="inherit")

        with patch("src.team_instanciator.resolvers.model_resolver.init_chat_model", return_value="model") as init_chat_model:
            resolved = ModelResolver(RuntimeConfiguration()).resolve(team, agent)

        self.assertEqual(resolved, "model")
        init_chat_model.assert_called_once_with(
            model="gpt-5.4-mini",
            streaming=True,
            stream_chunk_timeout=120.0,
            max_retries=0,
        )

    def test_model_and_reasoning_effort_can_come_from_runtime_or_process_env(self) -> None:
        team = SimpleNamespace(
            defaults=SimpleNamespace(
                model=SimpleNamespace(env="MODEL_ENV", default=None),
                reasoning_effort=SimpleNamespace(env="REASONING_ENV", default=None),
            )
        )
        agent = SimpleNamespace(id="speaker", model="inherit", reasoning_effort="inherit")

        with patch("src.team_instanciator.resolvers.model_resolver.init_chat_model", return_value="model") as init_chat_model:
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
            streaming=True,
            stream_chunk_timeout=120.0,
            max_retries=0,
            reasoning={"effort": "low", "summary": "auto"},
            use_responses_api=True,
            output_version="responses/v1",
        )

        with patch.dict("os.environ", {"MODEL_ENV": "gpt-process", "REASONING_ENV": ""}, clear=True):
            with patch("src.team_instanciator.resolvers.model_resolver.init_chat_model", return_value="model") as init_chat_model:
                self.assertEqual(ModelResolver(RuntimeConfiguration()).resolve(team, agent), "model")
            init_chat_model.assert_called_once_with(
                model="gpt-process",
                streaming=True,
                stream_chunk_timeout=120.0,
                max_retries=0,
            )

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

    def test_reliability_policy_wraps_base_chat_model_bindings_with_retry_metadata(self) -> None:
        model = RecordingChatModel()
        policy = ModelReliabilityPolicy(stream_idle_timeout_s=42, max_attempts=2, retry_backoff_initial_s=0, retry_backoff_max_s=0)

        wrapped = wrap_model_for_reliability(model, model_name="openai:gpt-test", policy=policy)
        self.assertIsInstance(wrapped, ReliableChatModel)

        bound = wrapped.bind_tools([])

        self.assertIs(bound, model.bound)
        self.assertEqual(
            model.bound.config_kwargs["metadata"],
            {
                "model_provider": "openai",
                "model_name": "openai:gpt-test",
                "model_reliability_max_attempts": 2,
                "model_reliability_timeout_mode": "stream_idle_timeout",
                "model_reliability_timeout_s": 42,
                "model_reliability_stream_idle_timeout": True,
            },
        )
        self.assertEqual(model.bound.retry_kwargs["stop_after_attempt"], 2)
        self.assertEqual(model.bound.retry_kwargs["exponential_jitter_params"]["initial"], 0)

    def test_reliability_policy_invalid_values_warn_and_fall_back(self) -> None:
        with self.assertLogs("src.team_instanciator.resolvers.model_reliability", level="WARNING"):
            policy = ModelReliabilityPolicy.from_configuration(
                RuntimeConfiguration(
                    {
                        "CODING_AGENTS_MODEL_STREAM_IDLE_TIMEOUT_S": "-1",
                        "CODING_AGENTS_MODEL_MAX_ATTEMPTS": "0",
                        "CODING_AGENTS_MODEL_RETRY_BACKOFF_INITIAL_S": "bad",
                    }
                )
            )

        self.assertEqual(policy.stream_idle_timeout_s, 120.0)
        self.assertEqual(policy.max_attempts, 1)
        self.assertEqual(policy.retry_backoff_initial_s, 1.0)

    def _team(self, *, model: str, reasoning_effort: str | None) -> SimpleNamespace:
        return SimpleNamespace(
            defaults=SimpleNamespace(
                model=SimpleNamespace(env=None, default=model),
                reasoning_effort=SimpleNamespace(env=None, default=reasoning_effort),
            )
        )


if __name__ == "__main__":
    unittest.main()
