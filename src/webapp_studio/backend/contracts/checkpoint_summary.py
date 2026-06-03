from __future__ import annotations

from pydantic import Field

from src.webapp_studio.backend.contracts.checkpoint_action_capabilities import CheckpointActionCapabilities
from src.webapp_studio.backend.contracts.contract_model import ContractModel
from src.webapp_studio.backend.contracts.types import JsonLike


class CheckpointSummary(ContractModel):
    id: str
    thread_id: str
    checkpoint_ns: str = ""
    parent_checkpoint_id: str | None = None
    seq: int
    created_at: str
    source: str
    metadata: dict[str, JsonLike] = Field(default_factory=dict)
    summary: dict[str, JsonLike] = Field(default_factory=dict)
    capabilities: CheckpointActionCapabilities = Field(default_factory=CheckpointActionCapabilities)
