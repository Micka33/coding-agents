from __future__ import annotations

import os
import unittest
from unittest.mock import patch

from src.team_instanciator.runtime_configuration import RuntimeConfiguration


class RuntimeConfigurationTests(unittest.TestCase):
    def test_merges_dicts_runtime_configuration_and_none_without_mutating_original(self) -> None:
        original = RuntimeConfiguration({"openai-api-key": "one"})

        merged_dict = original.merge({"OTHER": "two"})
        merged_config = original.merge(RuntimeConfiguration({"OPENAI_API_KEY": "three"}))
        merged_none = original.merge(None)

        self.assertEqual(original.as_dict(), {"openai-api-key": "one"})
        self.assertEqual(merged_dict.as_dict(), {"openai-api-key": "one", "OTHER": "two"})
        self.assertEqual(merged_config.get("OPENAI_API_KEY"), "three")
        self.assertEqual(merged_none.as_dict(), {"openai-api-key": "one"})

    def test_reads_normalized_values_process_environment_and_defaults(self) -> None:
        with patch.dict(os.environ, {"PROCESS_VALUE": "process", "NORMALIZED_VALUE": "normalized"}, clear=True):
            config = RuntimeConfiguration({"custom-value": "configured"})

            self.assertEqual(config.get("CUSTOM_VALUE"), "configured")
            self.assertEqual(config.get("PROCESS_VALUE"), "process")
            self.assertEqual(config.get("normalized-value"), "normalized")
            self.assertEqual(config.get("MISSING", "fallback"), "fallback")

    def test_resolves_model_and_tool_api_keys_by_provider(self) -> None:
        with patch.dict(os.environ, {"TAVILY_API_KEY": "tavily-env", "ANTHROPIC_API_KEY": "anthropic-env"}, clear=True):
            self.assertEqual(RuntimeConfiguration({"API_KEY": "generic"}).model_kwargs("openai:gpt-test"), {"api_key": "generic"})
            self.assertEqual(RuntimeConfiguration().model_kwargs("anthropic:claude-test"), {"api_key": "anthropic-env"})
            self.assertEqual(RuntimeConfiguration().model_kwargs("gpt-test"), {})
            self.assertEqual(RuntimeConfiguration().tool_api_key("tavily"), "tavily-env")
            self.assertIsNone(RuntimeConfiguration().tool_api_key("unknown"))


if __name__ == "__main__":
    unittest.main()
