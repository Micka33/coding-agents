from __future__ import annotations

from src.webapp_studio.backend.contracts.contract_model import ContractModel


class ConversationFileRefDto(ContractModel):
    id: str
    filename: str
    uri: str
    media_type: str | None = None
    size_bytes: int | None = None
    added_by: str | None = None
