from __future__ import annotations

from deepagents import (
    GeneralPurposeSubagentProfile,
    HarnessProfile,
    create_deep_agent,
    register_harness_profile,
)
from deepagents.graph import GENERAL_PURPOSE_SUBAGENT
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
from src.team_instanciator.factories.tool_visibility_factory import ToolVisibilityFactory
from src.team_instanciator.factories.tool_name_validator import ToolNameValidator
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
        tool_visibility_factory: ToolVisibilityFactory | None = None,
    ) -> None:
        self._model_resolver = model_resolver
        self._toolset_resolver = toolset_resolver
        self._backend_factory = backend_factory
        self._permissions_factory = permissions_factory
        self._memory_resolver = memory_resolver
        self._skills_resolver = skills_resolver
        self._tool_visibility_factory = tool_visibility_factory or ToolVisibilityFactory()
        self._tool_name_validator = ToolNameValidator()

    def create(
        self,
        team: TeamDefinition,
        agent: AgentDefinition,
        checkpointer_handle: CheckpointerHandle,
        tools: list[BaseTool],
        subagents: list[SubagentSpec] | None,
    ) -> RunnableGraph:
        model = self._model_resolver.resolve(team, agent)
        self._disable_default_general_purpose_subagent(model)
        permissions = self._permissions_factory.create(agent, team)
        effective_subagents = self._subagents(team, agent, permissions, subagents)
        resolved_tools = [*self._toolset_resolver.resolve_for_deepagents(team, agent), *tools]
        self._tool_name_validator.validate_unique(agent.id, resolved_tools)
        return create_deep_agent(
            name=agent.id,
            model=model,
            tools=resolved_tools,
            system_prompt=agent.prompt,
            subagents=effective_subagents,
            backend=self._backend_factory.create(team, agent),
            permissions=permissions,
            middleware=[
                self._tool_visibility_factory.create(
                    team,
                    agent,
                    task_available=bool(effective_subagents),
                )
            ],
            skills=self._skills_resolver.resolve(team, agent),
            memory=self._memory_resolver.resolve(team, agent),
            checkpointer=checkpointer_handle.checkpointer,
            debug=agent.debug is True,
        )

    def _subagents(
        self,
        team: TeamDefinition,
        agent: AgentDefinition,
        permissions: list[object],
        subagents: list[SubagentSpec] | None,
    ) -> list[SubagentSpec] | None:
        specs = list(subagents or [])
        if agent.enable_general_purpose_subagent and not self._has_general_purpose_subagent(specs):
            specs.append(
                {
                    **GENERAL_PURPOSE_SUBAGENT,
                    "permissions": permissions,
                    "middleware": [
                        self._tool_visibility_factory.create(
                            team,
                            agent,
                            task_available=False,
                        )
                    ],
                }
            )
        return specs or None

    def _has_general_purpose_subagent(self, subagents: list[SubagentSpec]) -> bool:
        return any(spec.get("name") == GENERAL_PURPOSE_SUBAGENT["name"] for spec in subagents)

    def _disable_default_general_purpose_subagent(self, model: object) -> None:
        key = self._harness_profile_key(model)
        if key is None:
            return
        register_harness_profile(
            key,
            HarnessProfile(general_purpose_subagent=GeneralPurposeSubagentProfile(enabled=False)),
        )

    def _harness_profile_key(self, model: object) -> str | None:
        if isinstance(model, str):
            return model
        model_name = (
            self._string_attr(model, "resolved_model_name")
            or self._string_attr(model, "model_name")
            or self._string_attr(model, "model")
        )
        if not model_name:
            return None
        if ":" in model_name:
            return model_name
        capabilities = getattr(model, "capabilities", None)
        provider = getattr(capabilities, "provider", None)
        if isinstance(provider, str) and provider and provider != "unknown":
            return f"{provider}:{model_name}"
        return None

    def _string_attr(self, value: object, attribute: str) -> str | None:
        raw = getattr(value, attribute, None)
        return raw if isinstance(raw, str) and raw else None
