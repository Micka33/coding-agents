from __future__ import annotations

from pydantic import Field

from src.webapp_studio.backend.contracts.contract_model import ContractModel


class HealthStatus(ContractModel):
    status: str = "ok"
    backend: str = "webapp_studio"
    api_version: str = "studio.v1"
    started_at: str
    versions: dict[str, str] = Field(default_factory=dict)
