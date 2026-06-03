from __future__ import annotations

import json
from typing import Literal

from pydantic import Field

from src.webapp_studio.backend.contracts.contract_model import ContractModel
from src.webapp_studio.backend.contracts.types import JsonLike


class StreamFrame(ContractModel):
    id: str
    event: str
    schema_version: Literal["studio.v1"] = "studio.v1"
    cursor: str
    payload: JsonLike = Field(default_factory=dict)

    def to_sse(self) -> str:
        data = self.model_dump(mode="json", include={"schema_version", "cursor", "payload"})
        return f"id: {self.id}\nevent: {self.event}\ndata: {json.dumps(data, separators=(',', ':'))}\n\n"
