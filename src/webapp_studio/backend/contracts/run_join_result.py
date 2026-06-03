from __future__ import annotations

from src.webapp_studio.backend.contracts.contract_model import ContractModel


class RunJoinResult(ContractModel):
    run_id: str
    cursor: str | None = None
    replay_available: bool
    stream_url: str
