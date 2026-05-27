from __future__ import annotations

import os
from typing import Any

from langchain.chat_models import init_chat_model

from coding_agents.team_loader.agent_definition import AgentDefinition
from coding_agents.team_loader.team_definition import TeamDefinition

from .runtime_configuration import RuntimeConfiguration
from .team_instanciator_error import TeamInstanciatorError


class ModelResolver:
    def __init__(self, configuration: RuntimeConfiguration | None = None) -> None:
        self._configuration = configuration or RuntimeConfiguration()

    def resolve(self, team: TeamDefinition, agent: AgentDefinition) -> Any:
        model = self._model_name(team, agent)
        reasoning_effort = self._reasoning_effort(team, agent)
        kwargs = self._configuration.model_kwargs(model)
        if reasoning_effort is not None:
            kwargs["reasoning_effort"] = reasoning_effort
        if not kwargs:
            return model
        return init_chat_model(model=model, **kwargs)

    def _model_name(self, team: TeamDefinition, agent: AgentDefinition) -> str:
        if agent.model and agent.model != "inherit":
            return agent.model
        env = team.defaults.model.env
        configured = self._configured_env_value(env)
        if configured:
            return configured
        if team.defaults.model.default:
            return team.defaults.model.default
        raise TeamInstanciatorError("Missing model configuration.")

    def _reasoning_effort(self, team: TeamDefinition, agent: AgentDefinition) -> str | None:
        if agent.reasoning_effort == "inherit":
            return self._team_reasoning_effort(team)
        return agent.reasoning_effort

    def _team_reasoning_effort(self, team: TeamDefinition) -> str | None:
        env = team.defaults.reasoning_effort.env
        configured = self._configured_env_value(env)
        if configured:
            return configured
        return team.defaults.reasoning_effort.default

    def _configured_env_value(self, env: str | None) -> str | None:
        if not env:
            return None
        value = self._configuration.get(env)
        if value:
            return str(value)
        if os.environ.get(env):
            return os.environ[env]
        return None
