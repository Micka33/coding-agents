from __future__ import annotations

from langchain_core.tools import StructuredTool

from src.team_loader.models.agent_definition import AgentDefinition
from src.team_loader.models.relation_definition import RelationDefinition
from src.team_loader.models.team_definition import TeamDefinition

from src.team_instanciator.core.agent_graph import AgentGraph
from src.team_instanciator.runtime.checkpointer_handle import CheckpointerHandle
from src.team_instanciator.factories.checkpoint_metadata_factory import CheckpointMetadataFactory
from src.team_instanciator.factories.deep_agent_factory import DeepAgentFactory
from src.team_instanciator.factories.relation_tool_factory import RelationToolFactory
from src.team_instanciator.factories.subagent_factory import SubagentFactory, SubagentSpec
from src.team_instanciator.runtime.branch_thread_resolver import BranchThreadResolver
from src.team_instanciator.runtime.thread_id_factory import ThreadIdFactory
from src.team_instanciator.runtime.tool_call_edge_recorder import ToolCallEdgeRecorder


class AgentGraphRegistry:
    def __init__(
        self,
        team: TeamDefinition,
        checkpointer_handle: CheckpointerHandle,
        deep_agent_factory: DeepAgentFactory,
        subagent_factory: SubagentFactory,
        relation_tool_factory: RelationToolFactory,
        thread_id_factory: ThreadIdFactory,
        checkpoint_metadata_factory: CheckpointMetadataFactory | None = None,
        tool_call_edge_recorder: ToolCallEdgeRecorder | None = None,
        branch_thread_resolver: BranchThreadResolver | None = None,
    ) -> None:
        self._team = team
        self._checkpointer_handle = checkpointer_handle
        self._deep_agent_factory = deep_agent_factory
        self._subagent_factory = subagent_factory
        self._relation_tool_factory = relation_tool_factory
        self._thread_id_factory = thread_id_factory
        self._checkpoint_metadata_factory = checkpoint_metadata_factory or CheckpointMetadataFactory()
        self._tool_call_edge_recorder = tool_call_edge_recorder or ToolCallEdgeRecorder(checkpointer_handle.connection)
        self._branch_thread_resolver = branch_thread_resolver
        self._graphs: dict[str, AgentGraph] = {}

    def graph(self, agent_id: str) -> AgentGraph:
        if agent_id not in self._graphs:
            self._graphs[agent_id] = self._create_graph(self._team.agents[agent_id])
        return self._graphs[agent_id]

    def _create_graph(self, agent: AgentDefinition) -> AgentGraph:
        graph = self._deep_agent_factory.create(
            self._team,
            agent,
            self._checkpointer_handle,
            self._relation_tools(agent),
            self._subagent_specs(agent),
        )
        metadata = (
            self._checkpoint_metadata_factory.entrypoint(self._team, agent)
            if agent.entrypoint
            else self._checkpoint_metadata_factory.direct_agent(self._team, agent)
        )
        return AgentGraph(graph, metadata)

    def _relation_tools(self, agent: AgentDefinition) -> list[StructuredTool]:
        return [
            self._relation_tool_factory.create(
                self._team,
                relation,
                self,
                self._thread_id_factory,
                self._checkpoint_metadata_factory,
                self._tool_call_edge_recorder,
                self._branch_thread_resolver,
                self._checkpointer_handle.async_runner,
            )
            for relation in self._relations_from(agent, "tool")
        ]

    def _subagent_specs(self, agent: AgentDefinition) -> list[SubagentSpec] | None:
        specs = [self._subagent_factory.create(self._team, self, relation.target) for relation in self._relations_from(agent, "subagent")]
        return specs or None

    def _relations_from(self, agent: AgentDefinition, relation_type: str) -> list[RelationDefinition]:
        return [relation for relation in self._team.relations if relation.source == agent.id and relation.relation == relation_type]
