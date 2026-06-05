from __future__ import annotations

from pydantic import Field

from src.webapp_studio.backend.contracts.contract_model import ContractModel
from src.webapp_studio.backend.contracts.types import JsonLike


class ConversationCreateRequest(ContractModel):
    team_id: str
    initial_message: str
    author_id: str = "human"
    attachments: list[dict[str, JsonLike]] = Field(default_factory=list)
    workspace_paths: list[str] = Field(default_factory=list)
    wait: bool = False
    client_message_id: str | None = None
