from __future__ import annotations

import logging

from langchain.chat_models import init_chat_model

from src.team_loader.models.agent_definition import AgentDefinition
from src.team_loader.models.team_definition import TeamDefinition

from src.team_instanciator.configuration.runtime_configuration import RuntimeConfiguration
from src.team_instanciator.errors.team_instanciator_error import TeamInstanciatorError


LOGGER = logging.getLogger(__name__)


class ModelResolver:
    def __init__(self, configuration: RuntimeConfiguration | None = None) -> None:
        self._configuration = configuration or RuntimeConfiguration()

    def resolve(self, team: TeamDefinition, agent: AgentDefinition) -> object:
        model = self._model_name(team, agent)
        raw_reasoning_effort = self._raw_reasoning_effort(team, agent)
        reasoning_effort = self._normalize_reasoning_effort(raw_reasoning_effort)
        kwargs = self._configuration.model_kwargs(model)
        if reasoning_effort is not None:
            kwargs.update(self._reasoning_kwargs(model, reasoning_effort))
        self._log_resolved_model(agent, model, raw_reasoning_effort, reasoning_effort, kwargs)
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

    def _raw_reasoning_effort(self, team: TeamDefinition, agent: AgentDefinition) -> str | None:
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
        return None

    def _normalize_reasoning_effort(self, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = str(value).strip()
        if not normalized:
            return None
        return normalized

    def _reasoning_kwargs(self, model: str, reasoning_effort: str) -> dict[str, object]:
        if self._is_openai_model(model):
            reasoning: dict[str, str] = {"effort": reasoning_effort}
            if reasoning_effort != "none":
                reasoning["summary"] = "auto"
            return {
                "reasoning": reasoning,
                "use_responses_api": True,
                "output_version": "responses/v1",
            }
        return {"reasoning_effort": reasoning_effort}

    def _is_openai_model(self, model: str) -> bool:
        if ":" in model:
            provider, _model_name = model.split(":", 1)
            return provider == "openai"
        return model.startswith(("gpt-", "chatgpt-", "o1", "o3", "o4"))

    def _log_resolved_model(
        self,
        agent: AgentDefinition,
        model: str,
        raw_reasoning_effort: str | None,
        reasoning_effort: str | None,
        kwargs: dict[str, object],
    ) -> None:
        safe_kwargs = {key: ("<redacted>" if key == "api_key" else value) for key, value in kwargs.items()}
        LOGGER.warning(
            "ModelResolver resolved agent=%s model=%s raw_reasoning_effort=%r "
            "effective_reasoning_effort=%r init_chat_model_kwargs=%r",
            agent.id,
            model,
            raw_reasoning_effort,
            reasoning_effort,
            safe_kwargs,
        )
