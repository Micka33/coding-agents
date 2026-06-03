from __future__ import annotations

from pydantic import Field

from src.webapp_studio.backend.contracts.contract_model import ContractModel
from src.webapp_studio.backend.contracts.types import JsonLike


class StudioError(ContractModel):
    code: str
    message: str
    field: str | None = None
    retryable: bool = False
    details: dict[str, JsonLike] = Field(default_factory=dict)
