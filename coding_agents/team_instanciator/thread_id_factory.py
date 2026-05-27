from __future__ import annotations

from coding_agents.team_loader.relation_definition import RelationDefinition

from .parsed_relation_thread_id import ParsedRelationThreadId


class ThreadIdFactory:
    def root(self, team_id: str) -> str:
        return team_id

    def relation(self, parent_thread_id: str, relation: RelationDefinition) -> str:
        tool_name = relation.tool_name or relation.relation
        return f"{parent_thread_id}:{relation.source}:{tool_name}:{relation.target}"

    def relation_pattern(self, relation: RelationDefinition) -> str:
        tool_name = relation.tool_name or relation.relation
        return f"{{parent_thread_id}}:{relation.source}:{tool_name}:{relation.target}"

    def parse_relation_thread_id(self, thread_id: str) -> ParsedRelationThreadId | None:
        parts = thread_id.rsplit(":", 3)
        if len(parts) != 4 or any(part == "" for part in parts):
            return None
        parent_thread_id, source_agent_id, tool_name, target_agent_id = parts
        return ParsedRelationThreadId(
            parent_thread_id=parent_thread_id,
            source_agent_id=source_agent_id,
            tool_name=tool_name,
            target_agent_id=target_agent_id,
        )
