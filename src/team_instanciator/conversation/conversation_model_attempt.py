from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, TypedDict


ModelAttemptStatus = Literal["running", "retrying", "success", "failed"]


class ConversationModelAttemptDict(TypedDict):
    id: str
    team_id: str
    conversation_id: str
    branch_id: str
    run_id: str
    agent_id: str
    provider: str
    model: str
    attempt_number: int
    max_attempts: int
    timeout_mode: str
    timeout_seconds: float
    started_at: str
    completed_at: str | None
    status: ModelAttemptStatus
    normalized_failure_code: str | None
    provider_error_type: str | None


@dataclass(frozen=True)
class ConversationModelAttempt:
    id: str
    team_id: str
    conversation_id: str
    branch_id: str
    run_id: str
    agent_id: str
    provider: str
    model: str
    attempt_number: int
    max_attempts: int
    timeout_mode: str
    timeout_seconds: float
    started_at: str
    completed_at: str | None = None
    status: ModelAttemptStatus = "running"
    normalized_failure_code: str | None = None
    provider_error_type: str | None = None

    def to_dict(self) -> ConversationModelAttemptDict:
        return {
            "id": self.id,
            "team_id": self.team_id,
            "conversation_id": self.conversation_id,
            "branch_id": self.branch_id,
            "run_id": self.run_id,
            "agent_id": self.agent_id,
            "provider": self.provider,
            "model": self.model,
            "attempt_number": self.attempt_number,
            "max_attempts": self.max_attempts,
            "timeout_mode": self.timeout_mode,
            "timeout_seconds": self.timeout_seconds,
            "started_at": self.started_at,
            "completed_at": self.completed_at,
            "status": self.status,
            "normalized_failure_code": self.normalized_failure_code,
            "provider_error_type": self.provider_error_type,
        }
