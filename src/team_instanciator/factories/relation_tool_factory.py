from __future__ import annotations

from langchain_core.tools import StructuredTool

from src.team_loader.models.relation_definition import RelationDefinition
from src.team_loader.models.team_definition import TeamDefinition

from src.team_instanciator.conversation.protocols import GraphRegistry
from src.team_instanciator.factories.checkpoint_metadata_factory import CheckpointMetadataFactory
from src.team_instanciator.tools.relation_tool import RelationTool
from src.team_instanciator.errors.team_instanciator_error import TeamInstanciatorError
from src.team_instanciator.runtime.thread_id_factory import ThreadIdFactory
from src.team_instanciator.runtime.tool_call_edge_recorder import ToolCallEdgeRecorder


class RelationToolFactory:
    def create(
        self,
        team: TeamDefinition,
        relation: RelationDefinition,
        registry: GraphRegistry,
        parent_thread_id: str,
        thread_id_factory: ThreadIdFactory,
        checkpoint_metadata_factory: CheckpointMetadataFactory | None = None,
        tool_call_edge_recorder: ToolCallEdgeRecorder | None = None,
    ) -> StructuredTool:
        if not relation.tool_name:
            raise TeamInstanciatorError(f"Relation tool from '{relation.source}' to '{relation.target}' has no tool_name.")
        metadata_factory = checkpoint_metadata_factory or CheckpointMetadataFactory()
        relation_tool = RelationTool(
            relation,
            registry,
            parent_thread_id,
            thread_id_factory,
            metadata_factory.tool_relation(team, relation),
            tool_call_edge_recorder,
        )
        return StructuredTool.from_function(
            relation_tool.run,
            name=relation.tool_name,
            description=relation.description or relation.tool_name or "Call a related agent.",
        )
