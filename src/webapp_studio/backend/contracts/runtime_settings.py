from __future__ import annotations

from src.webapp_studio.backend.contracts.contract_model import ContractModel


class RuntimeSettings(ContractModel):
    team_id: str
    conversation_id: str
    mention_hook_enabled: bool
    max_cascade_turns: int | None = None
