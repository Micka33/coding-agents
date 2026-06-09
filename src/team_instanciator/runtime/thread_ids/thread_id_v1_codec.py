from __future__ import annotations

from urllib.parse import quote, unquote

from src.team_loader.models.relation_definition import RelationDefinition

from src.team_instanciator.runtime.thread_ids.parsed_thread_id import ParsedThreadId


class ThreadIdV1Codec:
    _PREFIX = "ca"
    _VERSION = "v1"

    @property
    def prefix(self) -> str:
        return self._PREFIX

    @property
    def version(self) -> str:
        return self._VERSION

    def root(self, *, team_id: str, conversation_id: str) -> str:
        return f"{self.prefix}:{self.version}:team:{self._segment(team_id)}:conversation:{self._segment(conversation_id)}"

    def branch(self, parent_thread_id: str, branch_id: str) -> str:
        return f"{parent_thread_id}:branch:{self._segment(branch_id)}"

    def mention(self, parent_thread_id: str, agent_id: str) -> str:
        return f"{parent_thread_id}:mention:{self._segment(agent_id)}"

    def relation(self, parent_thread_id: str, relation: RelationDefinition) -> str:
        relation_id = self._segment(self.relation_id(relation))
        target = self._segment(relation.target)
        return f"{parent_thread_id}:relation:{relation_id}:agent:{target}"

    def relation_id(self, relation: RelationDefinition) -> str:
        relation_id = getattr(relation, "id", "")
        if isinstance(relation_id, str) and relation_id:
            return relation_id
        return f"{relation.source}:{relation.relation}:{relation.target}"

    def parse(self, thread_id: str) -> ParsedThreadId:
        parts = thread_id.split(":")
        if len(parts) < 6 or parts[:3] != [self.prefix, self.version, "team"] or parts[4] != "conversation":
            raise ValueError(f"Invalid thread id: {thread_id}")
        team_id = unquote(parts[3])
        conversation_id = unquote(parts[5])
        index = 6
        branch_id = None
        agent_id = None
        if index < len(parts):
            if parts[index] != "branch" or index + 1 >= len(parts):
                raise ValueError(f"Invalid thread id: {thread_id}")
            branch_id = unquote(parts[index + 1])
            index += 2
        if index < len(parts):
            if parts[index] != "mention" or index + 1 >= len(parts):
                raise ValueError(f"Invalid thread id: {thread_id}")
            agent_id = unquote(parts[index + 1])
            index += 2
        relations: list[tuple[str, str]] = []
        while index < len(parts):
            if parts[index] != "relation" or index + 3 >= len(parts) or parts[index + 2] != "agent":
                raise ValueError(f"Invalid thread id: {thread_id}")
            relations.append((unquote(parts[index + 1]), unquote(parts[index + 3])))
            index += 4
        relation_id = relations[-1][0] if relations else None
        target_agent_id = relations[-1][1] if relations else None
        return ParsedThreadId(
            version=self.version,
            team_id=team_id,
            conversation_id=conversation_id,
            branch_id=branch_id,
            agent_id=agent_id,
            relations=tuple(relations),
            relation_id=relation_id,
            target_agent_id=target_agent_id,
        )

    def segment(self, value: str) -> str:
        return self._segment(value)

    def _segment(self, value: str) -> str:
        return quote(value, safe="-._~")
