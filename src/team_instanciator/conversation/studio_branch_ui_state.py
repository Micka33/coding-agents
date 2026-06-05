from __future__ import annotations

from dataclasses import dataclass, field
from typing import TypedDict

from src.type_defs import JsonValue


class StudioBranchUiStateDict(TypedDict):
    team_id: str
    conversation_id: str
    branch_id: str
    participant_id: str
    draft_content: str
    outbox_state: JsonValue
    editing_event_id: str | None
    selected_agent_id: str | None
    scroll_anchor_event_id: str | None
    updated_at: str


@dataclass(frozen=True)
class StudioBranchUiState:
    team_id: str
    conversation_id: str
    branch_id: str
    participant_id: str
    draft_content: str = ""
    outbox_state: JsonValue = field(default_factory=list)
    editing_event_id: str | None = None
    selected_agent_id: str | None = None
    scroll_anchor_event_id: str | None = None
    updated_at: str = ""

    def to_dict(self) -> StudioBranchUiStateDict:
        return {
            "team_id": self.team_id,
            "conversation_id": self.conversation_id,
            "branch_id": self.branch_id,
            "participant_id": self.participant_id,
            "draft_content": self.draft_content,
            "outbox_state": self.outbox_state,
            "editing_event_id": self.editing_event_id,
            "selected_agent_id": self.selected_agent_id,
            "scroll_anchor_event_id": self.scroll_anchor_event_id,
            "updated_at": self.updated_at,
        }
