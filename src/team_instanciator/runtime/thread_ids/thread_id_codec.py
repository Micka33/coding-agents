from __future__ import annotations

from typing import Protocol

from src.team_loader.models.relation_definition import RelationDefinition

from src.team_instanciator.runtime.thread_ids.parsed_thread_id import ParsedThreadId


class ThreadIdCodec(Protocol):
    @property
    def prefix(self) -> str:
        ...

    @property
    def version(self) -> str:
        ...

    def root(self, *, team_id: str, conversation_id: str) -> str:
        ...

    def branch(self, parent_thread_id: str, branch_id: str) -> str:
        ...

    def mention(self, parent_thread_id: str, agent_id: str) -> str:
        ...

    def relation(self, parent_thread_id: str, relation: RelationDefinition) -> str:
        ...

    def relation_id(self, relation: RelationDefinition) -> str:
        ...

    def parse(self, thread_id: str) -> ParsedThreadId:
        ...

    def segment(self, value: str) -> str:
        ...
