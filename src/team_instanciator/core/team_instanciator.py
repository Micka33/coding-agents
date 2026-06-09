from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path

from src.type_defs import JsonObject
from src.team_loader.loading.team_loader import TeamLoader
from src.team_loader.resolvers.working_directory_resolver import WorkingDirectoryResolver

from src.team_instanciator.core.agent_graph_registry import AgentGraphRegistry
from src.team_instanciator.resolvers.agent_runtime_resolver import AgentRuntimeResolver
from src.team_instanciator.factories.backend_factory import BackendFactory
from src.team_instanciator.factories.checkpointer_factory import CheckpointerFactory
from src.team_instanciator.factories.checkpoint_metadata_factory import CheckpointMetadataFactory
from src.team_instanciator.factories.deep_agent_factory import DeepAgentFactory
from src.team_instanciator.conversation import MentionAwareTeam
from src.team_instanciator.core.instantiated_team import InstantiatedTeam
from src.team_instanciator.factories.langchain_agent_factory import LangChainAgentFactory
from src.team_instanciator.resolvers.memory_resolver import MemoryResolver
from src.team_instanciator.resolvers.model_resolver import ModelResolver
from src.team_instanciator.factories.permissions_factory import PermissionsFactory
from src.team_instanciator.factories.relation_tool_factory import RelationToolFactory
from src.team_instanciator.configuration.runtime_configuration import RuntimeConfiguration
from src.team_instanciator.configuration.runtime_configuration_validator import RuntimeConfigurationValidator
from src.team_instanciator.resolvers.skills_resolver import SkillsResolver
from src.team_instanciator.factories.subagent_factory import SubagentFactory
from src.team_instanciator.factories.tool_visibility_factory import ToolVisibilityFactory
from src.team_instanciator.runtime.thread_id_factory import ThreadIdFactory
from src.team_instanciator.runtime.tool_call_edge_recorder import ToolCallEdgeRecorder
from src.team_instanciator.runtime.branch_thread_resolver import BranchThreadResolver
from src.team_instanciator.manifest.team_runtime_manifest_builder import TeamRuntimeManifestBuilder
from src.team_instanciator.manifest.team_runtime_manifest_store import TeamRuntimeManifestStore
from src.team_instanciator.resolvers.toolset_resolver import ToolsetResolver


class TeamInstanciator:
    def __init__(
        self,
        team_loader: TeamLoader | None = None,
        config_variables: Mapping[str, object] | RuntimeConfiguration | None = None,
    ) -> None:
        self._team_loader = team_loader or TeamLoader()
        self._configuration = self._runtime_configuration(config_variables)

    def instantiate(
        self,
        team_file: str | Path,
        variables: JsonObject | None = None,
        config_variables: Mapping[str, object] | RuntimeConfiguration | None = None,
    ) -> InstantiatedTeam:
        configuration = self._configuration.merge(config_variables)
        team = self._team_loader.load(team_file, variables)
        RuntimeConfigurationValidator(configuration).validate(team)
        checkpointer_handle = CheckpointerFactory(configuration).create(team)
        model_resolver = ModelResolver(configuration)
        toolset_resolver = ToolsetResolver(configuration, checkpointer_handle)
        permissions_factory = PermissionsFactory()
        tool_visibility_factory = ToolVisibilityFactory(configuration)
        relation_tool_factory = RelationToolFactory()
        thread_id_factory = ThreadIdFactory()
        checkpoint_metadata_factory = CheckpointMetadataFactory()
        tool_call_edge_recorder = ToolCallEdgeRecorder(checkpointer_handle.connection)
        branch_thread_resolver = BranchThreadResolver(checkpointer_handle.connection, team.id)
        working_directory_resolver = WorkingDirectoryResolver()
        runtime_manifest = TeamRuntimeManifestBuilder(thread_id_factory).build(team)
        langchain_agent_factory = LangChainAgentFactory(model_resolver, toolset_resolver)
        subagent_factory = SubagentFactory(
            AgentRuntimeResolver(),
            langchain_agent_factory,
            toolset_resolver,
            relation_tool_factory,
            thread_id_factory,
            permissions_factory,
            tool_visibility_factory,
            checkpoint_metadata_factory,
            tool_call_edge_recorder,
            branch_thread_resolver,
        )
        deep_agent_factory = DeepAgentFactory(
            model_resolver,
            toolset_resolver,
            BackendFactory(configuration),
            permissions_factory,
            MemoryResolver(),
            SkillsResolver(configuration),
            tool_visibility_factory,
        )
        registry = AgentGraphRegistry(
            team,
            checkpointer_handle,
            deep_agent_factory,
            subagent_factory,
            relation_tool_factory,
            thread_id_factory,
            checkpoint_metadata_factory,
            tool_call_edge_recorder,
            branch_thread_resolver,
        )
        entrypoint = team.entrypoint()
        if entrypoint is None:
            checkpointer_handle.close()
            raise ValueError("Team has no entrypoint agent.")
        try:
            graph = registry.graph(entrypoint.id)
            TeamRuntimeManifestStore().persist(checkpointer_handle, runtime_manifest)
            conversation = (
                MentionAwareTeam(
                    team=team,
                    registry=registry,
                    checkpointer_handle=checkpointer_handle,
                    root_dir=working_directory_resolver.resolve_team(team),
                    conversation_id=team.id,
                    thread_id_factory=thread_id_factory,
                    checkpoint_metadata_factory=checkpoint_metadata_factory,
                )
                if getattr(team, "conversation", None) is not None
                else None
            )
        except Exception:
            checkpointer_handle.close()
            raise
        return InstantiatedTeam(
            team=team,
            graph=graph,
            checkpointer_handle=checkpointer_handle,
            runtime_manifest=runtime_manifest,
            conversation=conversation,
        )

    def _runtime_configuration(
        self,
        config_variables: Mapping[str, object] | RuntimeConfiguration | None,
    ) -> RuntimeConfiguration:
        if isinstance(config_variables, RuntimeConfiguration):
            return config_variables
        return RuntimeConfiguration(config_variables)
