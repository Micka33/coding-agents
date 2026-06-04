from __future__ import annotations

from typing import Literal

from src.webapp_studio.backend.contracts.contract_model import ContractModel


class ConversationRunDto(ContractModel):
    id: str
    team_id: str
    conversation_id: str
    branch_id: str
    agent_id: str
    logical_thread_key: str | None = None
    physical_thread_id: str | None = None
    status: Literal[
        "running",
        "success",
        "stopped",
        "failed",
        "empty",
        "interrupted",
        "cascade-limited",
        "skipped",
        "ignored",
    ]
    stop_kind: str | None = None
    snapshot_seq: int | None = None
    started_at: str
    completed_at: str | None = None
    stable_checkpoint_id: str | None = None
    latest_checkpoint_id: str | None = None
    checkpoint_stability: Literal["stable", "unstable", "unknown"] = "unknown"
    usable_for_fork: bool = False
    usable_for_continue: bool = False
    commit_state: Literal["pending", "committed", "orphaned"] = "pending"
