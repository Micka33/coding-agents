from __future__ import annotations

from typing import Literal

from src.webapp_studio.backend.contracts.contract_model import ContractModel


class ThreadFrontierDto(ContractModel):
    frontier_id: str
    team_id: str
    conversation_id: str
    branch_id: str
    event_id: str
    event_boundary: Literal["before", "after"]
    logical_thread_key: str
    physical_thread_id: str
    checkpoint_id: str | None = None
    parent_logical_thread_key: str | None = None
    usable_for_fork: bool = False
    usable_for_continue: bool = False
    created_at: str
