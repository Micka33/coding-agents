from __future__ import annotations

from src.team_loader.models.team_definition import TeamDefinition

from src.team_instanciator.configuration.runtime_configuration import RuntimeConfiguration
from src.team_instanciator.errors.team_instanciator_error import TeamInstanciatorError


class RuntimeConfigurationValidator:
    def __init__(self, configuration: RuntimeConfiguration) -> None:
        self._configuration = configuration

    def validate(self, team: TeamDefinition) -> None:
        missing = [
            *self._missing_model_value(team),
            *self._missing_reasoning_effort_value(team),
        ]
        if missing:
            names = ", ".join(missing)
            raise TeamInstanciatorError(
                f"Missing required runtime configuration: {names}. "
                "Provide it through the environment, a .env file, config_variables, or CLI --config."
            )

    def _missing_model_value(self, team: TeamDefinition) -> list[str]:
        if not self._uses_inherited_model(team):
            return []
        return self._missing_required_value(team.defaults.model.env, team.defaults.model.default)

    def _missing_reasoning_effort_value(self, team: TeamDefinition) -> list[str]:
        if not self._uses_inherited_reasoning_effort(team):
            return []
        return self._missing_required_value(team.defaults.reasoning_effort.env, team.defaults.reasoning_effort.default)

    def _missing_required_value(self, env: str | None, default: str | None) -> list[str]:
        if default is not None or not env:
            return []
        value = self._configuration.get(env)
        if value is None or str(value).strip() == "":
            return [env]
        return []

    def _uses_inherited_model(self, team: TeamDefinition) -> bool:
        return any(agent.model in {None, "inherit"} for agent in team.agents.values())

    def _uses_inherited_reasoning_effort(self, team: TeamDefinition) -> bool:
        return any(agent.reasoning_effort == "inherit" for agent in team.agents.values())
