from __future__ import annotations

from pydantic import Field

from src.webapp_studio.backend.contracts.contract_model import ContractModel
from src.webapp_studio.backend.contracts.types import JsonLike


class StudioBranchUiStateUpdateRequest(ContractModel):
    branch_id: str | None = None
    participant_id: str = "human"
    draft_content: str = ""
    outbox_state: JsonLike = Field(default_factory=list)
    editing_event_id: str | None = None
    selected_agent_id: str | None = None
    scroll_anchor_event_id: str | None = None
