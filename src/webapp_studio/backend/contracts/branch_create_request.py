from __future__ import annotations

from pydantic import Field

from src.webapp_studio.backend.contracts.contract_model import ContractModel
from src.webapp_studio.backend.contracts.types import JsonLike


class BranchCreateRequest(ContractModel):
    label: str | None = None
    checkpoint_id: str | None = None
    message_id: str | None = None
    edited_content: str | None = None
    metadata: dict[str, JsonLike] = Field(default_factory=dict)
