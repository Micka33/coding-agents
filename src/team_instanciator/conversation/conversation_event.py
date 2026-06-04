from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal, TypeAlias, TypedDict

from src.type_defs import JsonMapping, JsonObject

from .conversation_file_ref import ConversationFileRef, ConversationFileRefDict

AuthorKind: TypeAlias = Literal["human", "agent"]


class ConversationEventDict(TypedDict):
    id: str
    team_id: str
    conversation_id: str
    branch_id: str
    logical_message_id: str
    version_parent_event_id: str | None
    parent_event_id: str | None
    frontier_before_event_id: str | None
    frontier_after_event_id: str | None
    seq: int
    created_at: str
    author_id: str
    author_kind: AuthorKind
    content: str
    mentions: list[str]
    attachments: list[ConversationFileRefDict]
    source_thread_id: str | None
    source_message_id: str | None
    metadata: JsonObject


@dataclass(frozen=True)
class ConversationEvent:
    id: str
    team_id: str
    conversation_id: str
    seq: int
    created_at: str
    author_id: str
    author_kind: AuthorKind
    content: str
    mentions: tuple[str, ...]
    attachments: tuple[ConversationFileRef, ...] = ()
    source_thread_id: str | None = None
    source_message_id: str | None = None
    metadata: JsonMapping = field(default_factory=dict)
    branch_id: str = "branch_main"
    logical_message_id: str | None = None
    version_parent_event_id: str | None = None
    parent_event_id: str | None = None
    frontier_before_event_id: str | None = None
    frontier_after_event_id: str | None = None

    def to_dict(self) -> ConversationEventDict:
        return {
            "id": self.id,
            "team_id": self.team_id,
            "conversation_id": self.conversation_id,
            "branch_id": self.branch_id,
            "logical_message_id": self.logical_message_id or self.id,
            "version_parent_event_id": self.version_parent_event_id,
            "parent_event_id": self.parent_event_id,
            "frontier_before_event_id": self.frontier_before_event_id,
            "frontier_after_event_id": self.frontier_after_event_id,
            "seq": self.seq,
            "created_at": self.created_at,
            "author_id": self.author_id,
            "author_kind": self.author_kind,
            "content": self.content,
            "mentions": list(self.mentions),
            "attachments": [attachment.to_dict() for attachment in self.attachments],
            "source_thread_id": self.source_thread_id,
            "source_message_id": self.source_message_id,
            "metadata": dict(self.metadata),
        }
