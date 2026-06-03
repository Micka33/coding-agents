from __future__ import annotations

from typing import Literal

from pydantic import Field

from src.webapp_studio.backend.contracts.contract_model import ContractModel
from src.webapp_studio.backend.contracts.types import JsonLike


class CheckpointResumeRequest(ContractModel):
    mode: Literal["resume", "regenerate", "edit"] = "resume"
    edited_content: str | None = None
    metadata: dict[str, JsonLike] = Field(default_factory=dict)
