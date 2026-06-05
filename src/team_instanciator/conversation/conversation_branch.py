from __future__ import annotations

from dataclasses import dataclass
from typing import Literal


@dataclass
class ConversationBranch:
    id: str
    team_id: str
    conversation_id: str
    label: str
    parent_branch_id: str | None
    origin_checkpoint_id: str | None
    origin_event_id: str | None
    origin_logical_message_id: str | None
    origin_previous_event_id: str | None
    origin_event_seq: int | None
    created_at: str
    current: bool
    status: Literal["derived", "persisted"] = "persisted"
    head_checkpoint_id: str | None = None
    archived_at: str | None = None

    def to_dict(self) -> dict[str, object]:
        return {
            "id": self.id,
            "team_id": self.team_id,
            "conversation_id": self.conversation_id,
            "label": self.label,
            "parent_branch_id": self.parent_branch_id,
            "origin_checkpoint_id": self.origin_checkpoint_id,
            "origin_event_id": self.origin_event_id,
            "origin_logical_message_id": self.origin_logical_message_id,
            "origin_previous_event_id": self.origin_previous_event_id,
            "origin_event_seq": self.origin_event_seq,
            "created_at": self.created_at,
            "current": self.current,
            "status": self.status,
            "head_checkpoint_id": self.head_checkpoint_id,
            "archived_at": self.archived_at,
        }
