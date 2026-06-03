from __future__ import annotations

from typing import Literal

from src.webapp_studio.backend.contracts.contract_model import ContractModel


class QueueItem(ContractModel):
    id: str
    conversation_id: str
    agent_id: str
    status: Literal["pending", "running", "cancelled", "failed", "completed"]
    position: int | None = None
    enqueued_at: str | None = None
    updated_at: str | None = None
    message_event_id: str | None = None
    can_cancel: bool = False
    error: str | None = None
