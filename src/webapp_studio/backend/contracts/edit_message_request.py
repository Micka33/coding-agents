from __future__ import annotations

from src.webapp_studio.backend.contracts.contract_model import ContractModel


class EditMessageRequest(ContractModel):
    content: str
    author_id: str = "human"
    wait: bool = False
