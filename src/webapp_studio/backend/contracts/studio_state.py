from __future__ import annotations

from pydantic import Field

from src.webapp_studio.backend.contracts.activity_snapshot import ActivitySnapshot
from src.webapp_studio.backend.contracts.contract_model import ContractModel
from src.webapp_studio.backend.contracts.conversation_snapshot import ConversationSnapshot
from src.webapp_studio.backend.contracts.generated_ui_spec import GeneratedUiSpec
from src.webapp_studio.backend.contracts.history_snapshot import HistorySnapshot
from src.webapp_studio.backend.contracts.interrupt_request import InterruptRequest
from src.webapp_studio.backend.contracts.queue_item import QueueItem
from src.webapp_studio.backend.contracts.run_summary import RunSummary
from src.webapp_studio.backend.contracts.runtime_settings import RuntimeSettings
from src.webapp_studio.backend.contracts.studio_branch_ui_state_dto import StudioBranchUiStateDto


class StudioState(ContractModel):
    team_id: str
    conversation_id: str
    participants: list[str] = Field(default_factory=list)
    participant_aliases: dict[str, list[str]] = Field(default_factory=dict)
    runtime: RuntimeSettings
    conversation: ConversationSnapshot
    activity: ActivitySnapshot
    runs: list[RunSummary] = Field(default_factory=list)
    queue: list[QueueItem] = Field(default_factory=list)
    interrupts: list[InterruptRequest] = Field(default_factory=list)
    history: HistorySnapshot
    ui_state: StudioBranchUiStateDto
    generated_ui: list[GeneratedUiSpec] = Field(default_factory=list)
