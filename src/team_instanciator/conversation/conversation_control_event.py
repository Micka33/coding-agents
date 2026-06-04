from __future__ import annotations

from dataclasses import dataclass
from typing import TypedDict


class ConversationControlEventDict(TypedDict):
    id: str
    team_id: str
    conversation_id: str
    branch_id: str
    logical_thread_key: str
    physical_thread_id: str
    parent_run_id: str | None
    kind: str
    content: str
    created_at: str


@dataclass(frozen=True)
class ConversationControlEvent:
    id: str
    team_id: str
    conversation_id: str
    branch_id: str
    logical_thread_key: str
    physical_thread_id: str
    parent_run_id: str | None
    kind: str
    content: str
    created_at: str

    def to_dict(self) -> ConversationControlEventDict:
        return {
            "id": self.id,
            "team_id": self.team_id,
            "conversation_id": self.conversation_id,
            "branch_id": self.branch_id,
            "logical_thread_key": self.logical_thread_key,
            "physical_thread_id": self.physical_thread_id,
            "parent_run_id": self.parent_run_id,
            "kind": self.kind,
            "content": self.content,
            "created_at": self.created_at,
        }
