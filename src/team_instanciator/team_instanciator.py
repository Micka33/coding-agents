from __future__ import annotations

from pathlib import Path
from typing import Any

from src.team_loader.team_loader import TeamLoader

from .agent_graph_registry import AgentGraphRegistry
from .agent_runtime_resolver import AgentRuntimeResolver
from .backend_factory import BackendFactory
from .checkpointer_factory import CheckpointerFactory
from .checkpoint_metadata_factory import CheckpointMetadataFactory
from .deep_agent_factory import DeepAgentFactory
from .instantiated_team import InstantiatedTeam
from .langchain_agent_factory import LangChainAgentFactory
from .memory_resolver import MemoryResolver
from .model_resolver import ModelResolver
from .permissions_factory import PermissionsFactory
from .relation_tool_factory import RelationToolFactory
from .runtime_configuration import RuntimeConfiguration
from .runtime_configuration_validator import RuntimeConfigurationValidator
from .skills_resolver import SkillsResolver
from .subagent_factory import SubagentFactory
from .thread_id_factory import ThreadIdFactory
from .team_runtime_manifest_builder import TeamRuntimeManifestBuilder
from .team_runtime_manifest_store import TeamRuntimeManifestStore
from .toolset_resolver import ToolsetResolver


class TeamInstanciator:
    def __init__(
        self,
        team_loader: TeamLoader | None = None,
        config_variables: dict[str, Any] | RuntimeConfiguration | None = None,
    ) -> None:
        self._team_loader = team_loader or TeamLoader()
        self._configuration = self._runtime_configuration(config_variables)

    def instantiate(
        self,
        team_file: str | Path,
        variables: dict[str, Any] | None = None,
        config_variables: dict[str, Any] | RuntimeConfiguration | None = None,
    ) -> InstantiatedTeam:
        configuration = self._configuration.merge(config_variables)
        team = self._team_loader.load(team_file, variables)
        RuntimeConfigurationValidator(configuration).validate(team)
        checkpointer_handle = CheckpointerFactory(configuration).create(team)
        model_resolver = ModelResolver(configuration)
        toolset_resolver = ToolsetResolver(configuration, checkpointer_handle)
        relation_tool_factory = RelationToolFactory()
        thread_id_factory = ThreadIdFactory()
        checkpoint_metadata_factory = CheckpointMetadataFactory()
        runtime_manifest = TeamRuntimeManifestBuilder(thread_id_factory).build(team)
        langchain_agent_factory = LangChainAgentFactory(model_resolver, toolset_resolver)
        subagent_factory = SubagentFactory(
            AgentRuntimeResolver(),
            langchain_agent_factory,
            toolset_resolver,
            relation_tool_factory,
            thread_id_factory,
            checkpoint_metadata_factory,
        )
        deep_agent_factory = DeepAgentFactory(
            model_resolver,
            toolset_resolver,
            BackendFactory(configuration),
            PermissionsFactory(),
            MemoryResolver(),
            SkillsResolver(configuration),
        )
        registry = AgentGraphRegistry(
            team,
            checkpointer_handle,
            deep_agent_factory,
            subagent_factory,
            relation_tool_factory,
            thread_id_factory,
            checkpoint_metadata_factory,
        )
        entrypoint = team.entrypoint()
        if entrypoint is None:
            checkpointer_handle.close()
            raise ValueError("Team has no entrypoint agent.")
        try:
            graph = registry.graph(entrypoint.id)
            TeamRuntimeManifestStore().persist(checkpointer_handle, runtime_manifest)
        except Exception:
            checkpointer_handle.close()
            raise
        return InstantiatedTeam(
            team=team,
            graph=graph,
            checkpointer_handle=checkpointer_handle,
            runtime_manifest=runtime_manifest,
        )

    def _runtime_configuration(
        self,
        config_variables: dict[str, Any] | RuntimeConfiguration | None,
    ) -> RuntimeConfiguration:
        if isinstance(config_variables, RuntimeConfiguration):
            return config_variables
        return RuntimeConfiguration(config_variables)
