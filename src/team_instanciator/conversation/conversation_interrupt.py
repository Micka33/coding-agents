from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

from src.type_defs import JsonObject

ConversationInterruptDecision = Literal["approve", "reject", "edit", "respond"]
ConversationInterruptKind = Literal["approve", "edit", "respond", "review"]
ConversationInterruptStatus = Literal["pending", "resolved"]


@dataclass
class ConversationInterrupt:
    id: str
    team_id: str
    conversation_id: str
    created_at: str
    kind: ConversationInterruptKind
    branch_id: str = "branch_main"
    payload: JsonObject = field(default_factory=dict)
    status: ConversationInterruptStatus = "pending"
    decisions: tuple[JsonObject, ...] = ()
    run_id: str | None = None
    agent_id: str | None = None
    checkpoint_id: str | None = None

    def to_dict(self) -> dict[str, object]:
        return {
            "id": self.id,
            "team_id": self.team_id,
            "conversation_id": self.conversation_id,
            "branch_id": self.branch_id,
            "run_id": self.run_id,
            "agent_id": self.agent_id,
            "checkpoint_id": self.checkpoint_id,
            "created_at": self.created_at,
            "kind": self.kind,
            "payload": dict(self.payload),
            "status": self.status,
            "decisions": [dict(decision) for decision in self.decisions],
        }
