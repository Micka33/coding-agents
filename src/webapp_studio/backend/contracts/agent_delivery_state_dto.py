from __future__ import annotations

from src.webapp_studio.backend.contracts.contract_model import ContractModel


class AgentDeliveryStateDto(ContractModel):
    team_id: str
    conversation_id: str
    agent_id: str
    last_delivered_seq: int
    running: bool
    queued: bool
    queued_after_seq: int | None = None
    current_run_id: str | None = None
    current_snapshot_seq: int | None = None
    stop_requested: bool
    last_identity_refresh_seq: int
    token_estimate_since_identity_refresh: int
