from __future__ import annotations

from typing import Literal

from pydantic import Field

from src.webapp_studio.backend.contracts.contract_model import ContractModel
from src.webapp_studio.backend.contracts.types import JsonLike


class InterruptResumeRequest(ContractModel):
    decision: Literal["approve", "reject", "edit", "respond"]
    response: str | None = None
    edited_payload: dict[str, JsonLike] = Field(default_factory=dict)
