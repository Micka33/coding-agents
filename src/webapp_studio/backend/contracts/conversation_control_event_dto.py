from __future__ import annotations

from src.webapp_studio.backend.contracts.contract_model import ContractModel


class ConversationControlEventDto(ContractModel):
    id: str
    team_id: str
    conversation_id: str
    branch_id: str
    logical_thread_key: str
    physical_thread_id: str
    parent_run_id: str | None = None
    kind: str
    content: str
    created_at: str
