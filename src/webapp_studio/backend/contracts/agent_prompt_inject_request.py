from __future__ import annotations

from src.webapp_studio.backend.contracts.contract_model import ContractModel


class AgentPromptInjectRequest(ContractModel):
    content: str
    wait: bool = False
