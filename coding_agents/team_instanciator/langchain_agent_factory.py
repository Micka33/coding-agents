from __future__ import annotations

from langchain.agents import create_agent

from coding_agents.team_loader.agent_definition import AgentDefinition
from coding_agents.team_loader.team_definition import TeamDefinition

from .model_resolver import ModelResolver
from .toolset_resolver import ToolsetResolver


class LangChainAgentFactory:
    def __init__(self, model_resolver: ModelResolver, toolset_resolver: ToolsetResolver) -> None:
        self._model_resolver = model_resolver
        self._toolset_resolver = toolset_resolver

    def create(self, team: TeamDefinition, agent: AgentDefinition) -> object:
        return create_agent(
            model=self._model_resolver.resolve(team, agent),
            tools=self._toolset_resolver.resolve_for_langchain(team, agent),
            system_prompt=agent.prompt,
            name=agent.name,
            debug=agent.debug is True,
        )
