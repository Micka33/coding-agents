from __future__ import annotations

from typing import Literal

from src.webapp_studio.backend.contracts.contract_model import ContractModel


class ConversationBranchThreadDto(ContractModel):
    team_id: str
    conversation_id: str
    branch_id: str
    logical_thread_key: str
    physical_thread_id: str
    forked_from_branch_id: str | None = None
    forked_from_thread_id: str | None = None
    forked_from_checkpoint_id: str | None = None
    created_by_commit_id: str | None = None
    status: Literal["active", "orphaned"] = "active"
