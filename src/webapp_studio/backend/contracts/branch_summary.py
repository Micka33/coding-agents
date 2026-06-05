from __future__ import annotations

from typing import Literal

from src.webapp_studio.backend.contracts.contract_model import ContractModel


class BranchSummary(ContractModel):
    id: str
    label: str
    parent_branch_id: str | None = None
    origin_checkpoint_id: str | None = None
    origin_event_id: str | None = None
    origin_logical_message_id: str | None = None
    origin_previous_event_id: str | None = None
    origin_event_seq: int | None = None
    created_at: str
    current: bool
    status: Literal["derived", "persisted"]
    head_checkpoint_id: str | None = None
