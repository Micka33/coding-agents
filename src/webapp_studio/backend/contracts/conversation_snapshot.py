from __future__ import annotations

from pydantic import Field

from src.webapp_studio.backend.contracts.agent_delivery_state_dto import AgentDeliveryStateDto
from src.webapp_studio.backend.contracts.contract_model import ContractModel
from src.webapp_studio.backend.contracts.conversation_delivery_dto import ConversationDeliveryDto
from src.webapp_studio.backend.contracts.conversation_event_dto import ConversationEventDto


class ConversationSnapshot(ContractModel):
    events: list[ConversationEventDto] = Field(default_factory=list)
    deliveries: list[ConversationDeliveryDto] = Field(default_factory=list)
    agent_states: list[AgentDeliveryStateDto] = Field(default_factory=list)
