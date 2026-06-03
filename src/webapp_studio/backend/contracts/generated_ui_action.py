from __future__ import annotations

from typing import Literal

from pydantic import Field

from src.webapp_studio.backend.contracts.contract_model import ContractModel
from src.webapp_studio.backend.contracts.types import JsonLike


class GeneratedUiAction(ContractModel):
    description: str = ""
    input_schema: dict[str, JsonLike] = Field(default_factory=dict)
    confirmation_required: bool = False
    confirmation: dict[str, JsonLike] | None = None
    audit: Literal["record", "none"] = "record"
