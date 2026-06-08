from __future__ import annotations

from typing import Literal

from src.webapp_studio.backend.contracts.contract_model import ContractModel


class ConversationModelAttemptDto(ContractModel):
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
    status: Literal["running", "retrying", "success", "failed"] = "running"
    normalized_failure_code: str | None = None
    provider_error_type: str | None = None
