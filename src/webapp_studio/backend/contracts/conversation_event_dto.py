from __future__ import annotations

from typing import Literal

from pydantic import Field

from src.webapp_studio.backend.contracts.contract_model import ContractModel
from src.webapp_studio.backend.contracts.conversation_file_ref_dto import ConversationFileRefDto
from src.webapp_studio.backend.contracts.types import JsonLike


class ConversationEventDto(ContractModel):
    id: str
    team_id: str
    conversation_id: str
    branch_id: str = "branch_main"
    logical_message_id: str | None = None
    version_parent_event_id: str | None = None
    parent_event_id: str | None = None
    seq: int
    created_at: str
    author_id: str
    author_kind: Literal["human", "agent"]
    content: str
    mentions: list[str] = Field(default_factory=list)
    attachments: list[ConversationFileRefDto] = Field(default_factory=list)
    source_thread_id: str | None = None
    source_message_id: str | None = None
    metadata: dict[str, JsonLike] = Field(default_factory=dict)
