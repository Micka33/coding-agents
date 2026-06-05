from __future__ import annotations

from typing import Literal

from src.webapp_studio.backend.contracts.contract_model import ContractModel


class ConversationDeliveryDto(ContractModel):
    id: str
    team_id: str
    conversation_id: str
    branch_id: str = "branch_main"
    agent_id: str
    run_id: str | None = None
    snapshot_seq: int | None = None
    status: Literal["cascade-limited", "empty", "failed", "ignored", "interrupted", "skipped", "stopped", "success"]
    created_at: str
    completed_at: str | None = None
    error: str | None = None
