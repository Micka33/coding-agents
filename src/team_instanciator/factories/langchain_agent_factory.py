from __future__ import annotations

from langchain.agents import create_agent

from src.team_loader.models.agent_definition import AgentDefinition
from src.team_loader.models.team_definition import TeamDefinition

from src.team_instanciator.core.agent_graph import RunnableGraph
from src.team_instanciator.resolvers.model_resolver import ModelResolver
from src.team_instanciator.resolvers.toolset_resolver import ToolsetResolver


class LangChainAgentFactory:
    def __init__(self, model_resolver: ModelResolver, toolset_resolver: ToolsetResolver) -> None:
        self._model_resolver = model_resolver
        self._toolset_resolver = toolset_resolver

    def create(self, team: TeamDefinition, agent: AgentDefinition) -> RunnableGraph:
        return create_agent(
            model=self._model_resolver.resolve(team, agent),
            tools=self._toolset_resolver.resolve_for_langchain(team, agent),
            system_prompt=agent.prompt,
            name=agent.id,
            debug=agent.debug is True,
        )
