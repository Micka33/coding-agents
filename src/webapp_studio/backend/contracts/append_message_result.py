from __future__ import annotations

from pydantic import Field

from src.webapp_studio.backend.contracts.contract_model import ContractModel
from src.webapp_studio.backend.contracts.conversation_delivery_dto import ConversationDeliveryDto
from src.webapp_studio.backend.contracts.conversation_event_dto import ConversationEventDto


class AppendMessageResult(ContractModel):
    event: ConversationEventDto
    deliveries: list[ConversationDeliveryDto] = Field(default_factory=list)
    failures: list[ConversationDeliveryDto] = Field(default_factory=list)
