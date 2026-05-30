from __future__ import annotations

from typing import NotRequired, TypedDict

from langchain_core.tools import BaseTool, StructuredTool

from src.team_loader.models.team_definition import TeamDefinition

from src.team_instanciator.conversation.protocols import GraphRegistry
from src.team_instanciator.core.agent_graph import RunnableGraph
from src.team_instanciator.resolvers.agent_runtime_resolver import AgentRuntimeResolver
from src.team_instanciator.factories.checkpoint_metadata_factory import CheckpointMetadataFactory
from src.team_instanciator.factories.langchain_agent_factory import LangChainAgentFactory
from src.team_instanciator.factories.relation_tool_factory import RelationToolFactory
from src.team_instanciator.runtime.runnable_config_metadata_injector import RunnableConfigMetadataInjector
from src.team_instanciator.runtime.thread_id_factory import ThreadIdFactory
from src.team_instanciator.resolvers.toolset_resolver import ToolsetResolver


class SubagentSpec(TypedDict):
    name: str
    description: str
    runnable: NotRequired[RunnableGraph]
    system_prompt: NotRequired[str]
    tools: NotRequired[list[BaseTool]]


class SubagentFactory:
    def __init__(
        self,
        runtime_resolver: AgentRuntimeResolver,
        langchain_agent_factory: LangChainAgentFactory,
        toolset_resolver: ToolsetResolver,
        relation_tool_factory: RelationToolFactory,
        thread_id_factory: ThreadIdFactory,
        checkpoint_metadata_factory: CheckpointMetadataFactory | None = None,
    ) -> None:
        self._runtime_resolver = runtime_resolver
        self._langchain_agent_factory = langchain_agent_factory
        self._toolset_resolver = toolset_resolver
        self._relation_tool_factory = relation_tool_factory
        self._thread_id_factory = thread_id_factory
        self._checkpoint_metadata_factory = checkpoint_metadata_factory or CheckpointMetadataFactory()
        self._metadata_injector = RunnableConfigMetadataInjector()

    def create(self, team: TeamDefinition, registry: GraphRegistry, agent_id: str) -> SubagentSpec:
        agent = team.agents[agent_id]
        if self._runtime_resolver.subagent_runtime(agent) == "langchain":
            metadata = self._checkpoint_metadata_factory.task_subagent_type(team, agent)
            return {
                "name": agent.name,
                "description": agent.description or agent.name,
                "runnable": self._langchain_agent_factory.create(team, agent).with_config(
                    {"configurable": self._metadata_injector.inject(None, metadata)["metadata"]}
                ),
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

    def _relation_tools(self, team: TeamDefinition, registry: GraphRegistry, agent_id: str) -> list[StructuredTool]:
        return [
            self._relation_tool_factory.create(
                team,
                relation,
                registry,
                self._thread_id_factory.root(team.id),
                self._thread_id_factory,
                self._checkpoint_metadata_factory,
            )
            for relation in team.relations
            if relation.source == agent_id and relation.relation == "tool"
        ]
