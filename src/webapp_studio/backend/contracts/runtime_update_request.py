from __future__ import annotations

from src.webapp_studio.backend.contracts.contract_model import ContractModel


class RuntimeUpdateRequest(ContractModel):
    mention_hook_enabled: bool | None = None
    max_cascade_turns: int | None = None
