from __future__ import annotations

import uuid
from typing import Literal

from pydantic import Field

from src.webapp_studio.backend.contracts.contract_model import ContractModel
from src.webapp_studio.backend.contracts.studio_capabilities import StudioCapabilities
from src.webapp_studio.backend.contracts.studio_error import StudioError
from src.webapp_studio.backend.contracts.types import JsonLike


class StudioEnvelope(ContractModel):
    schema_version: Literal["studio.v1"] = "studio.v1"
    request_id: str = Field(default_factory=lambda: f"req_{uuid.uuid4().hex}")
    capabilities: StudioCapabilities = Field(default_factory=StudioCapabilities)
    data: JsonLike = Field(default_factory=dict)
    errors: list[StudioError] = Field(default_factory=list)

    @classmethod
    def ok(cls, data: JsonLike, *, capabilities: StudioCapabilities | None = None) -> "StudioEnvelope":
        return cls(data={} if data is None else data, capabilities=capabilities or StudioCapabilities())

    @classmethod
    def failed(cls, error: StudioError, *, capabilities: StudioCapabilities | None = None) -> "StudioEnvelope":
        return cls(data={}, errors=[error], capabilities=capabilities or StudioCapabilities())
