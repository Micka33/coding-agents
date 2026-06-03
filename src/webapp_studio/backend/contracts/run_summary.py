from __future__ import annotations

from typing import Literal

from pydantic import Field

from src.webapp_studio.backend.contracts.contract_model import ContractModel
from src.webapp_studio.backend.contracts.types import JsonLike


class RunSummary(ContractModel):
    id: str
    conversation_id: str
    agent_id: str | None = None
    status: Literal["queued", "running", "completed", "failed", "stopped", "superseded", "unknown"]
    created_at: str | None = None
    updated_at: str | None = None
    completed_at: str | None = None
    checkpoint_id: str | None = None
    cursor: str | None = None
    metadata: dict[str, JsonLike] = Field(default_factory=dict)
