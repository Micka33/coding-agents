from __future__ import annotations

from langchain_core.tools import StructuredTool

from coding_agents.team_loader.relation_definition import RelationDefinition
from coding_agents.team_loader.team_definition import TeamDefinition

from .checkpoint_metadata_factory import CheckpointMetadataFactory
from .relation_tool import RelationTool
from .team_instanciator_error import TeamInstanciatorError
from .thread_id_factory import ThreadIdFactory


class RelationToolFactory:
    def create(
        self,
        team: TeamDefinition,
        relation: RelationDefinition,
        registry: object,
        parent_thread_id: str,
        thread_id_factory: ThreadIdFactory,
        checkpoint_metadata_factory: CheckpointMetadataFactory | None = None,
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
        )
        return StructuredTool.from_function(
            relation_tool.run,
            name=relation.tool_name,
            description=relation.description or relation.tool_name or "Call a related agent.",
        )
