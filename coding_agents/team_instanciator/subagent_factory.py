from __future__ import annotations

from typing import Any

from coding_agents.team_loader.team_definition import TeamDefinition

from .agent_runtime_resolver import AgentRuntimeResolver
from .langchain_agent_factory import LangChainAgentFactory
from .relation_tool_factory import RelationToolFactory
from .thread_id_factory import ThreadIdFactory
from .toolset_resolver import ToolsetResolver


class SubagentFactory:
    def __init__(
        self,
        runtime_resolver: AgentRuntimeResolver,
        langchain_agent_factory: LangChainAgentFactory,
        toolset_resolver: ToolsetResolver,
        relation_tool_factory: RelationToolFactory,
        thread_id_factory: ThreadIdFactory,
    ) -> None:
        self._runtime_resolver = runtime_resolver
        self._langchain_agent_factory = langchain_agent_factory
        self._toolset_resolver = toolset_resolver
        self._relation_tool_factory = relation_tool_factory
        self._thread_id_factory = thread_id_factory

    def create(self, team: TeamDefinition, registry: object, agent_id: str) -> dict[str, Any]:
        agent = team.agents[agent_id]
        if self._runtime_resolver.subagent_runtime(agent) == "langchain":
            return {
                "name": agent.name,
                "description": agent.description or agent.name,
                "runnable": self._langchain_agent_factory.create(team, agent),
            }
        return {
            "name": agent.name,
            "description": agent.description or agent.name,
            "system_prompt": agent.prompt,
            "tools": [
                *self._toolset_resolver.resolve_for_deepagents(team, agent),
                *self._relation_tools(team, registry, agent_id),
            ],
        }

    def _relation_tools(self, team: TeamDefinition, registry: object, agent_id: str) -> list[Any]:
        return [
            self._relation_tool_factory.create(
                relation,
                registry,
                self._thread_id_factory.root(team.id),
                self._thread_id_factory,
            )
            for relation in team.relations
            if relation.source == agent_id and relation.relation == "tool"
        ]
