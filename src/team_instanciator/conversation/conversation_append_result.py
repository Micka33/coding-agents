from __future__ import annotations

from dataclasses import dataclass

from .conversation_delivery import ConversationDelivery
from .conversation_event import ConversationEvent


@dataclass(frozen=True)
class ConversationAppendResult:
    event: ConversationEvent
    deliveries: tuple[ConversationDelivery, ...]

    @property
    def failures(self) -> tuple[ConversationDelivery, ...]:
        return tuple(delivery for delivery in self.deliveries if delivery.status in {"failed", "empty", "cascade-limited"})
