from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, TypeAlias, TypedDict

DeliveryStatus: TypeAlias = Literal[
    "cascade-limited",
    "empty",
    "failed",
    "ignored",
    "skipped",
    "stopped",
    "success",
]


class ConversationDeliveryDict(TypedDict):
    id: str
    team_id: str
    conversation_id: str
    agent_id: str
    run_id: str | None
    snapshot_seq: int | None
    status: DeliveryStatus
    created_at: str
    completed_at: str | None
    error: str | None


@dataclass(frozen=True)
class ConversationDelivery:
    id: str
    team_id: str
    conversation_id: str
    agent_id: str
    run_id: str | None
    snapshot_seq: int | None
    status: DeliveryStatus
    created_at: str
    completed_at: str | None = None
    error: str | None = None

    def to_dict(self) -> ConversationDeliveryDict:
        return {
            "id": self.id,
            "team_id": self.team_id,
            "conversation_id": self.conversation_id,
            "agent_id": self.agent_id,
            "run_id": self.run_id,
            "snapshot_seq": self.snapshot_seq,
            "status": self.status,
            "created_at": self.created_at,
            "completed_at": self.completed_at,
            "error": self.error,
        }
