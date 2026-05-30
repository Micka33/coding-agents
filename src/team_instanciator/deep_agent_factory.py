from __future__ import annotations

from typing import Any

from deepagents import create_deep_agent

from src.team_loader.agent_definition import AgentDefinition
from src.team_loader.team_definition import TeamDefinition

from .backend_factory import BackendFactory
from .checkpointer_handle import CheckpointerHandle
from .memory_resolver import MemoryResolver
from .model_resolver import ModelResolver
from .permissions_factory import PermissionsFactory
from .skills_resolver import SkillsResolver
from .toolset_resolver import ToolsetResolver


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
        tools: list[Any],
        subagents: list[dict[str, Any]] | None,
    ) -> object:
        return create_deep_agent(
            name=agent.name,
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
