from __future__ import annotations

from typing import NotRequired, TypedDict

from deepagents.middleware.filesystem import FilesystemPermission
from langchain.agents.middleware.types import AgentMiddleware
from langchain_core.tools import BaseTool, StructuredTool

from src.team_loader.models.team_definition import TeamDefinition

from src.team_instanciator.conversation.protocols import GraphRegistry
from src.team_instanciator.core.agent_graph import RunnableGraph
from src.team_instanciator.resolvers.agent_runtime_resolver import AgentRuntimeResolver
from src.team_instanciator.factories.checkpoint_metadata_factory import CheckpointMetadataFactory
from src.team_instanciator.factories.langchain_agent_factory import LangChainAgentFactory
from src.team_instanciator.factories.permissions_factory import PermissionsFactory
from src.team_instanciator.factories.relation_tool_factory import RelationToolFactory
from src.team_instanciator.factories.tool_visibility_factory import ToolVisibilityFactory
from src.team_instanciator.factories.tool_name_validator import ToolNameValidator
from src.team_instanciator.resolvers.skills_resolver import SkillsResolver
from src.team_instanciator.runtime.async_checkpointer_loop import AsyncCheckpointerLoop
from src.team_instanciator.runtime.branch_thread_resolver import BranchThreadResolver
from src.team_instanciator.runtime.runnable_config_metadata_injector import RunnableConfigMetadataInjector
from src.team_instanciator.runtime.thread_id_factory import ThreadIdFactory
from src.team_instanciator.runtime.tool_call_edge_recorder import ToolCallEdgeRecorder
from src.team_instanciator.resolvers.toolset_resolver import ToolsetResolver


class SubagentSpec(TypedDict):
    name: str
    description: str
    runnable: NotRequired[RunnableGraph]
    system_prompt: NotRequired[str]
    tools: NotRequired[list[BaseTool]]
    middleware: NotRequired[list[AgentMiddleware]]
    permissions: NotRequired[list[FilesystemPermission]]
    skills: NotRequired[list[tuple[str, str]]]


class SubagentFactory:
    def __init__(
        self,
        runtime_resolver: AgentRuntimeResolver,
        langchain_agent_factory: LangChainAgentFactory,
        toolset_resolver: ToolsetResolver,
        relation_tool_factory: RelationToolFactory,
        thread_id_factory: ThreadIdFactory,
        permissions_factory: PermissionsFactory | None = None,
        tool_visibility_factory: ToolVisibilityFactory | None = None,
        checkpoint_metadata_factory: CheckpointMetadataFactory | None = None,
        tool_call_edge_recorder: ToolCallEdgeRecorder | None = None,
        branch_thread_resolver: BranchThreadResolver | None = None,
        async_runner: AsyncCheckpointerLoop | None = None,
        skills_resolver: SkillsResolver | None = None,
    ) -> None:
        self._runtime_resolver = runtime_resolver
        self._langchain_agent_factory = langchain_agent_factory
        self._toolset_resolver = toolset_resolver
        self._relation_tool_factory = relation_tool_factory
        self._thread_id_factory = thread_id_factory
        self._permissions_factory = permissions_factory or PermissionsFactory()
        self._tool_visibility_factory = tool_visibility_factory or ToolVisibilityFactory()
        self._checkpoint_metadata_factory = checkpoint_metadata_factory or CheckpointMetadataFactory()
        self._tool_call_edge_recorder = tool_call_edge_recorder
        self._branch_thread_resolver = branch_thread_resolver
        self._async_runner = async_runner
        self._skills_resolver = skills_resolver or SkillsResolver()
        self._metadata_injector = RunnableConfigMetadataInjector()
        self._tool_name_validator = ToolNameValidator()

    def create(self, team: TeamDefinition, registry: GraphRegistry, agent_id: str) -> SubagentSpec:
        agent = team.agents[agent_id]
        if self._runtime_resolver.subagent_runtime(agent) == "langchain":
            metadata = self._checkpoint_metadata_factory.task_subagent_type(team, agent)
            return {
                "name": agent.id,
                "description": agent.description or agent.id,
                "runnable": self._langchain_agent_factory.create(team, agent).with_config(
                    {"configurable": self._metadata_injector.inject(None, metadata)["metadata"]}
                ),
            }
        tools = [
            *self._toolset_resolver.resolve_for_deepagents(team, agent),
            *self._relation_tools(team, registry, agent_id),
        ]
        self._tool_name_validator.validate_unique(agent.id, tools)
        spec: SubagentSpec = {
            "name": agent.id,
            "description": agent.description or agent.id,
            "system_prompt": agent.prompt,
            "tools": tools,
            "permissions": self._permissions_factory.create(agent, team),
            "middleware": [
                self._tool_visibility_factory.create(
                    team,
                    agent,
                    task_available=False,
                )
            ],
        }
        skills = self._skills_resolver.resolve(team, agent)
        if skills is not None:
            spec["skills"] = skills
        return spec

    def _relation_tools(self, team: TeamDefinition, registry: GraphRegistry, agent_id: str) -> list[StructuredTool]:
        return [
            self._relation_tool_factory.create(
                team,
                relation,
                registry,
                self._thread_id_factory,
                self._checkpoint_metadata_factory,
                self._tool_call_edge_recorder,
                self._branch_thread_resolver,
                self._async_runner,
            )
            for relation in team.relations
            if relation.source == agent_id and relation.relation == "tool"
        ]
