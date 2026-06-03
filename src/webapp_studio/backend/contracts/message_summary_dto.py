from __future__ import annotations

from pydantic import Field

from src.webapp_studio.backend.contracts.contract_model import ContractModel
from src.webapp_studio.backend.contracts.types import JsonLike


class MessageSummaryDto(ContractModel):
    type: str
    name: str | None = None
    content: str
    tool_calls: JsonLike = Field(default_factory=list)
