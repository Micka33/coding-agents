from __future__ import annotations

from dataclasses import dataclass
from typing import TypedDict


class AgentDeliveryStateDict(TypedDict):
    team_id: str
    conversation_id: str
    agent_id: str
    last_delivered_seq: int
    running: bool
    queued: bool
    queued_after_seq: int | None
    current_run_id: str | None
    current_snapshot_seq: int | None
    stop_requested: bool
    last_identity_refresh_seq: int
    token_estimate_since_identity_refresh: int


@dataclass
class AgentDeliveryState:
    team_id: str
    conversation_id: str
    agent_id: str
    last_delivered_seq: int = 0
    running: bool = False
    queued: bool = False
    queued_after_seq: int | None = None
    current_run_id: str | None = None
    current_snapshot_seq: int | None = None
    stop_requested: bool = False
    last_identity_refresh_seq: int = 0
    token_estimate_since_identity_refresh: int = 0

    def to_dict(self) -> AgentDeliveryStateDict:
        return {
            "team_id": self.team_id,
            "conversation_id": self.conversation_id,
            "agent_id": self.agent_id,
            "last_delivered_seq": self.last_delivered_seq,
            "running": self.running,
            "queued": self.queued,
            "queued_after_seq": self.queued_after_seq,
            "current_run_id": self.current_run_id,
            "current_snapshot_seq": self.current_snapshot_seq,
            "stop_requested": self.stop_requested,
            "last_identity_refresh_seq": self.last_identity_refresh_seq,
            "token_estimate_since_identity_refresh": self.token_estimate_since_identity_refresh,
        }
