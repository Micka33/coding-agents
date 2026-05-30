from __future__ import annotations

from deepagents import create_deep_agent
from langchain_core.tools import BaseTool

from src.team_loader.models.agent_definition import AgentDefinition
from src.team_loader.models.team_definition import TeamDefinition

from src.team_instanciator.core.agent_graph import RunnableGraph
from src.team_instanciator.factories.backend_factory import BackendFactory
from src.team_instanciator.runtime.checkpointer_handle import CheckpointerHandle
from src.team_instanciator.resolvers.memory_resolver import MemoryResolver
from src.team_instanciator.resolvers.model_resolver import ModelResolver
from src.team_instanciator.factories.permissions_factory import PermissionsFactory
from src.team_instanciator.factories.subagent_factory import SubagentSpec
from src.team_instanciator.resolvers.skills_resolver import SkillsResolver
from src.team_instanciator.resolvers.toolset_resolver import ToolsetResolver


class DeepAgentFactory:
    def __init__(
        self,
        model_resolver: ModelResolver,
        toolset_resolver: ToolsetResolver,
        backend_factory: BackendFactory,
        permissions_factory: PermissionsFactory,
        memory_resolver: MemoryResolver,
        skills_resolver: SkillsResolver,
    ) -> None:
        self._model_resolver = model_resolver
        self._toolset_resolver = toolset_resolver
        self._backend_factory = backend_factory
        self._permissions_factory = permissions_factory
        self._memory_resolver = memory_resolver
        self._skills_resolver = skills_resolver

    def create(
        self,
        team: TeamDefinition,
        agent: AgentDefinition,
        checkpointer_handle: CheckpointerHandle,
        tools: list[BaseTool],
        subagents: list[SubagentSpec] | None,
    ) -> RunnableGraph:
        return create_deep_agent(
            name=agent.id,
            model=self._model_resolver.resolve(team, agent),
            tools=[*self._toolset_resolver.resolve_for_deepagents(team, agent), *tools],
            system_prompt=agent.prompt,
            subagents=subagents,
            backend=self._backend_factory.create(team, agent),
            permissions=self._permissions_factory.create(agent),
            skills=self._skills_resolver.resolve(team, agent),
            memory=self._memory_resolver.resolve(team, agent),
            checkpointer=checkpointer_handle.checkpointer,
            debug=agent.debug is True,
        )
