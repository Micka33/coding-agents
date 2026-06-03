from __future__ import annotations

from pydantic import Field

from src.webapp_studio.backend.contracts.contract_model import ContractModel
from src.webapp_studio.backend.contracts.message_summary_dto import MessageSummaryDto


class PrivateThreadDto(ContractModel):
    agent_id: str | None = None
    thread_id: str
    messages: list[MessageSummaryDto] = Field(default_factory=list)
