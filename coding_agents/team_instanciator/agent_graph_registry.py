from __future__ import annotations

from typing import Any

from coding_agents.team_loader.agent_definition import AgentDefinition
from coding_agents.team_loader.relation_definition import RelationDefinition
from coding_agents.team_loader.team_definition import TeamDefinition

from .checkpointer_handle import CheckpointerHandle
from .deep_agent_factory import DeepAgentFactory
from .relation_tool_factory import RelationToolFactory
from .subagent_factory import SubagentFactory
from .thread_id_factory import ThreadIdFactory


class AgentGraphRegistry:
    def __init__(
        self,
        team: TeamDefinition,
        checkpointer_handle: CheckpointerHandle,
        deep_agent_factory: DeepAgentFactory,
        subagent_factory: SubagentFactory,
        relation_tool_factory: RelationToolFactory,
        thread_id_factory: ThreadIdFactory,
    ) -> None:
        self._team = team
        self._checkpointer_handle = checkpointer_handle
        self._deep_agent_factory = deep_agent_factory
        self._subagent_factory = subagent_factory
        self._relation_tool_factory = relation_tool_factory
        self._thread_id_factory = thread_id_factory
        self._graphs: dict[str, Any] = {}

    def graph(self, agent_id: str) -> Any:
        if agent_id not in self._graphs:
            self._graphs[agent_id] = self._create_graph(self._team.agents[agent_id])
        return self._graphs[agent_id]

    def _create_graph(self, agent: AgentDefinition) -> Any:
        return self._deep_agent_factory.create(
            self._team,
            agent,
            self._checkpointer_handle,
            self._relation_tools(agent),
            self._subagent_specs(agent),
        )

    def _relation_tools(self, agent: AgentDefinition) -> list[Any]:
        return [
            self._relation_tool_factory.create(
                relation,
                self,
                self._thread_id_factory.root(self._team.id),
                self._thread_id_factory,
            )
            for relation in self._relations_from(agent, "tool")
        ]

    def _subagent_specs(self, agent: AgentDefinition) -> list[dict[str, Any]] | None:
        specs = [self._subagent_factory.create(self._team, self, relation.target) for relation in self._relations_from(agent, "subagent")]
        return specs or None

    def _relations_from(self, agent: AgentDefinition, relation_type: str) -> list[RelationDefinition]:
        return [relation for relation in self._team.relations if relation.source == agent.id and relation.relation == relation_type]
