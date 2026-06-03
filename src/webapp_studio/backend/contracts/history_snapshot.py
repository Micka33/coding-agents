from __future__ import annotations

from pydantic import Field

from src.webapp_studio.backend.contracts.branch_summary import BranchSummary
from src.webapp_studio.backend.contracts.checkpoint_summary import CheckpointSummary
from src.webapp_studio.backend.contracts.contract_model import ContractModel


class HistorySnapshot(ContractModel):
    current_branch_id: str = "branch_main"
    checkpoints: list[CheckpointSummary] = Field(default_factory=list)
    branches: list[BranchSummary] = Field(default_factory=list)
