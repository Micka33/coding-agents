from __future__ import annotations

from urllib.parse import quote, unquote

from src.team_loader.models.relation_definition import RelationDefinition

from src.team_instanciator.runtime.parsed_relation_thread_id import ParsedRelationThreadId


class ThreadIdFactory:
    def root(self, team_id: str) -> str:
        return team_id

    def branch(self, parent_thread_id: str, branch_id: str) -> str:
        return f"{parent_thread_id}:branch:{branch_id}"

    def branch_id_from_thread_id(self, thread_id: str) -> str | None:
        parts = thread_id.split(":")
        for index, part in enumerate(parts[:-1]):
            if part == "branch" and parts[index + 1]:
                return parts[index + 1]
        return None

    def logical_thread_key(self, physical_thread_id: str) -> str:
        parts = physical_thread_id.split(":")
        for index, part in enumerate(parts[:-1]):
            if part == "branch":
                return ":".join([*parts[:index], *parts[index + 2 :]])
        return physical_thread_id

    def relation_id(self, relation: RelationDefinition) -> str:
        relation_id = getattr(relation, "id", "")
        if isinstance(relation_id, str) and relation_id:
            return relation_id
        return f"{relation.source}:{relation.relation}:{relation.target}"

    def relation(self, parent_thread_id: str, relation: RelationDefinition) -> str:
        relation_id = self._segment(self.relation_id(relation))
        target = self._segment(relation.target)
        return f"{parent_thread_id}:relation:{relation_id}:agent:{target}"

    def mention(self, parent_thread_id: str, agent_id: str) -> str:
        return f"{parent_thread_id}:mention:{agent_id}"

    def mention_pattern(self, agent_id: str) -> str:
        return f"{{parent_thread_id}}:mention:{agent_id}"

    def relation_pattern(self, relation: RelationDefinition) -> str:
        relation_id = self._segment(self.relation_id(relation))
        target = self._segment(relation.target)
        return f"{{parent_thread_id}}:relation:{relation_id}:agent:{target}"

    def parse_relation_thread_id(self, thread_id: str) -> ParsedRelationThreadId | None:
        marker = ":relation:"
        target_marker = ":agent:"
        if marker in thread_id and target_marker in thread_id:
            parent_thread_id, tail = thread_id.split(marker, maxsplit=1)
            relation_segment, target_segment = tail.rsplit(target_marker, maxsplit=1)
            if parent_thread_id and relation_segment and target_segment:
                return ParsedRelationThreadId(
                    parent_thread_id=parent_thread_id,
                    relation_id=unquote(relation_segment),
                    target_agent_id=unquote(target_segment),
                )

        parts = thread_id.rsplit(":", 3)
        if len(parts) != 4 or any(part == "" for part in parts):
            return None
        parent_thread_id, source_agent_id, tool_name, target_agent_id = parts
        return ParsedRelationThreadId(
            parent_thread_id=parent_thread_id,
            relation_id=f"{source_agent_id}:{tool_name}:{target_agent_id}",
            source_agent_id=source_agent_id,
            tool_name=tool_name,
            target_agent_id=target_agent_id,
        )

    def _segment(self, value: str) -> str:
        return quote(value, safe="-._~")
