from __future__ import annotations

from dataclasses import dataclass
from typing import TypedDict


class ConversationRuntimeStateDict(TypedDict):
    team_id: str
    conversation_id: str
    mention_hook_enabled: bool
    max_cascade_turns: int | None


@dataclass
class ConversationRuntimeState:
    team_id: str
    conversation_id: str
    mention_hook_enabled: bool = True
    max_cascade_turns: int | None = None

    def to_dict(self) -> ConversationRuntimeStateDict:
        return {
            "team_id": self.team_id,
            "conversation_id": self.conversation_id,
            "mention_hook_enabled": self.mention_hook_enabled,
            "max_cascade_turns": self.max_cascade_turns,
        }
