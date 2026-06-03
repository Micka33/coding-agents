from __future__ import annotations

from typing import Literal

from pydantic import Field

from src.webapp_studio.backend.contracts.contract_model import ContractModel
from src.webapp_studio.backend.contracts.types import JsonLike


class InterruptRequest(ContractModel):
    id: str
    run_id: str | None = None
    agent_id: str | None = None
    checkpoint_id: str | None = None
    created_at: str
    kind: Literal["approve", "edit", "respond", "review"]
    payload: dict[str, JsonLike] = Field(default_factory=dict)
    status: Literal["pending", "resolved"] = "pending"
    decisions: list[dict[str, JsonLike]] = Field(default_factory=list)
