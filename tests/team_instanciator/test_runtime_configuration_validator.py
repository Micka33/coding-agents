from __future__ import annotations

import unittest

from src.team_instanciator.runtime_configuration import RuntimeConfiguration
from src.team_instanciator.runtime_configuration_validator import RuntimeConfigurationValidator
from src.team_instanciator.team_instanciator_error import TeamInstanciatorError
from tests.support import agent, defaults, team


class RuntimeConfigurationValidatorTests(unittest.TestCase):
    def test_validate_passes_when_agents_use_explicit_values_or_defaults_exist(self) -> None:
        explicit_team = team(
            agents={"entry": agent("entry", entrypoint=True, model="openai:gpt-test", reasoning_effort=None)},
            team_defaults=defaults(model_env="MODEL_ENV", model_default=None, reasoning_env="REASONING_ENV", reasoning_default="low"),
        )
        defaulted_team = team(
            agents={"entry": agent("entry", entrypoint=True, model="inherit", reasoning_effort="inherit")},
            team_defaults=defaults(model_env="MODEL_ENV", model_default="openai:gpt-default", reasoning_env=None, reasoning_default=None),
        )

        RuntimeConfigurationValidator(RuntimeConfiguration()).validate(explicit_team)
        RuntimeConfigurationValidator(RuntimeConfiguration()).validate(defaulted_team)

    def test_validate_reports_missing_inherited_model_and_reasoning_effort_env_values(self) -> None:
        team_config = team(
            agents={"entry": agent("entry", entrypoint=True, model="inherit", reasoning_effort="inherit")},
            team_defaults=defaults(model_env="MODEL_ENV", model_default=None, reasoning_env="REASONING_ENV", reasoning_default=None),
        )

        with self.assertRaisesRegex(TeamInstanciatorError, "MODEL_ENV, REASONING_ENV"):
            RuntimeConfigurationValidator(RuntimeConfiguration({"MODEL_ENV": "", "REASONING_ENV": " "})).validate(team_config)

        RuntimeConfigurationValidator(RuntimeConfiguration({"MODEL_ENV": "openai:gpt-test", "REASONING_ENV": "low"})).validate(team_config)


if __name__ == "__main__":
    unittest.main()
