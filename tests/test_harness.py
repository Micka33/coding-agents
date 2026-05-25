from __future__ import annotations

import unittest
from types import SimpleNamespace
from unittest.mock import patch

from coding_agents.harness import disable_default_general_purpose_subagent


class HarnessProfileTests(unittest.TestCase):
    def test_string_model_registers_exact_and_provider_disable_profile(self) -> None:
        with patch("coding_agents.harness.register_harness_profile") as register:
            disable_default_general_purpose_subagent("openai:gpt-5.4")

        self.assertEqual([call.args[0] for call in register.call_args_list], ["openai:gpt-5.4", "openai"])
        for call in register.call_args_list:
            profile = call.args[1]
            self.assertIsNotNone(profile.general_purpose_subagent)
            self.assertFalse(profile.general_purpose_subagent.enabled)

    def test_prebuilt_model_registers_derived_provider_fallback_when_available(self) -> None:
        model = SimpleNamespace(model_provider="openai", model_name="gpt-5.4")
        with (
            patch("coding_agents.harness.register_harness_profile") as register,
            patch("deepagents._models.get_model_provider", return_value="openai"),
            patch("deepagents._models.get_model_identifier", return_value="gpt-5.4"),
        ):
            disable_default_general_purpose_subagent(model)  # type: ignore[arg-type]

        self.assertEqual([call.args[0] for call in register.call_args_list], ["openai:gpt-5.4", "openai"])


if __name__ == "__main__":
    unittest.main()
