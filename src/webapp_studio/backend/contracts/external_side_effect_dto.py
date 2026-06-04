from __future__ import annotations

from pydantic import Field

from src.webapp_studio.backend.contracts.contract_model import ContractModel
from src.webapp_studio.backend.contracts.types import JsonLike


class ExternalSideEffectDto(ContractModel):
    id: str
    team_id: str
    conversation_id: str
    branch_id: str
    run_id: str | None = None
    agent_id: str | None = None
    tool_call_id: str | None = None
    kind: str
    target: str
    audit_payload: dict[str, JsonLike] = Field(default_factory=dict)
    not_rewindable: bool = True
    created_at: str
