from __future__ import annotations

from typing import Literal

from pydantic import Field

from src.webapp_studio.backend.contracts.contract_model import ContractModel
from src.webapp_studio.backend.contracts.generated_ui_action import GeneratedUiAction
from src.webapp_studio.backend.contracts.types import JsonLike


class GeneratedUiSpec(ContractModel):
    id: str
    version: str = "studio.generated-ui.v1"
    root: str
    elements: dict[str, dict[str, JsonLike]] = Field(default_factory=dict)
    state: dict[str, JsonLike] = Field(default_factory=dict)
    actions: dict[str, GeneratedUiAction] = Field(default_factory=dict)
    status: Literal["pending", "valid", "invalid"] = "pending"
    errors: list[str] = Field(default_factory=list)
    created_at: str
    updated_at: str | None = None
