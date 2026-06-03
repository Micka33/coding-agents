from __future__ import annotations

from pydantic import Field

from src.webapp_studio.backend.contracts.contract_model import ContractModel
from src.webapp_studio.backend.contracts.types import JsonLike


class AppendMessageRequest(ContractModel):
    content: str
    author_id: str = "human"
    attachments: list[dict[str, JsonLike]] = Field(default_factory=list)
    wait: bool = False
    client_message_id: str | None = None
