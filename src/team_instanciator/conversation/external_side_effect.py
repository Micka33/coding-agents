from __future__ import annotations

from dataclasses import dataclass, field
from typing import TypedDict

from src.type_defs import JsonObject


class ExternalSideEffectDict(TypedDict):
    id: str
    team_id: str
    conversation_id: str
    branch_id: str
    run_id: str | None
    agent_id: str | None
    tool_call_id: str | None
    kind: str
    target: str
    audit_payload: JsonObject
    not_rewindable: bool
    created_at: str


@dataclass(frozen=True)
class ExternalSideEffect:
    id: str
    team_id: str
    conversation_id: str
    branch_id: str
    run_id: str | None
    agent_id: str | None
    tool_call_id: str | None
    kind: str
    target: str
    audit_payload: JsonObject = field(default_factory=dict)
    not_rewindable: bool = True
    created_at: str = ""

    def to_dict(self) -> ExternalSideEffectDict:
        return {
            "id": self.id,
            "team_id": self.team_id,
            "conversation_id": self.conversation_id,
            "branch_id": self.branch_id,
            "run_id": self.run_id,
            "agent_id": self.agent_id,
            "tool_call_id": self.tool_call_id,
            "kind": self.kind,
            "target": self.target,
            "audit_payload": dict(self.audit_payload),
            "not_rewindable": self.not_rewindable,
            "created_at": self.created_at,
        }
