from __future__ import annotations

from src.team_loader.models.relation_definition import RelationDefinition

from src.team_instanciator.runtime.parsed_relation_thread_id import ParsedRelationThreadId
from src.team_instanciator.runtime.thread_ids import ParsedThreadId, ThreadIdCodec, ThreadIdV1Codec


class ThreadIdFactory:
    def __init__(self, writer: ThreadIdCodec | None = None, parsers: tuple[ThreadIdCodec, ...] | None = None) -> None:
        self._writer = writer or ThreadIdV1Codec()
        registered_parsers = parsers or (self._writer,)
        self._parsers = {parser.version: parser for parser in registered_parsers}

    def root(self, *, team_id: str, conversation_id: str) -> str:
        return self._writer.root(team_id=team_id, conversation_id=conversation_id)

    def branch(self, parent_thread_id: str, branch_id: str) -> str:
        parent = self.parse(parent_thread_id)
        parser = self._parser_for(parent.version)
        return parser.branch(parent_thread_id, branch_id)

    def branch_id_from_thread_id(self, thread_id: str) -> str | None:
        return self.parse(thread_id).branch_id

    def logical_thread_key(self, physical_thread_id: str) -> str:
        parsed = self.parse(physical_thread_id)
        if parsed.agent_id is None:
            raise ValueError("Thread id does not identify a mention thread.")
        key = self.logical_mention(parsed.agent_id)
        for relation_id, target_agent_id in parsed.relations:
            key = self._logical_relation_from_values(key, relation_id, target_agent_id)
        return key

    def relation_id(self, relation: RelationDefinition) -> str:
        return self._writer.relation_id(relation)

    def relation(self, parent_thread_id: str, relation: RelationDefinition) -> str:
        parent = self.parse(parent_thread_id)
        parser = self._parser_for(parent.version)
        return parser.relation(parent_thread_id, relation)

    def mention(self, parent_thread_id: str, agent_id: str) -> str:
        parent = self.parse(parent_thread_id)
        parser = self._parser_for(parent.version)
        return parser.mention(parent_thread_id, agent_id)

    def logical_mention(self, agent_id: str) -> str:
        return f"mention:{self._writer.segment(agent_id)}"

    def logical_relation(self, parent_logical_key: str, relation: RelationDefinition) -> str:
        return self._logical_relation_from_values(parent_logical_key, self.relation_id(relation), relation.target)

    def mention_pattern(self, agent_id: str) -> str:
        return self.logical_mention(agent_id)

    def relation_pattern(self, relation: RelationDefinition) -> str:
        return self.logical_relation("{parent_logical_key}", relation)

    def parse(self, thread_id: str) -> ParsedThreadId:
        return self._parser_for(self._version_from(thread_id)).parse(thread_id)

    def parse_relation_thread_id(self, thread_id: str) -> ParsedRelationThreadId | None:
        marker = ":relation:"
        try:
            parsed = self.parse(thread_id)
        except ValueError:
            return None
        if parsed.relation_id is None or parsed.target_agent_id is None or marker not in thread_id:
            return None
        parent_thread_id = thread_id.rsplit(marker, maxsplit=1)[0]
        return ParsedRelationThreadId(
            parent_thread_id=parent_thread_id,
            relation_id=parsed.relation_id,
            target_agent_id=parsed.target_agent_id,
        )

    def _logical_relation_from_values(self, parent_logical_key: str, relation_id: str, target_agent_id: str) -> str:
        relation_segment = self._writer.segment(relation_id)
        target_segment = self._writer.segment(target_agent_id)
        return f"{parent_logical_key}:relation:{relation_segment}:agent:{target_segment}"

    def _version_from(self, thread_id: str) -> str:
        parts = thread_id.split(":", maxsplit=2)
        if len(parts) < 2 or parts[0] != self._writer.prefix:
            raise ValueError(f"Invalid thread id: {thread_id}")
        return parts[1]

    def _parser_for(self, version: str) -> ThreadIdCodec:
        parser = self._parsers.get(version)
        if parser is None:
            raise ValueError(f"Unsupported thread id version: {version}")
        return parser
