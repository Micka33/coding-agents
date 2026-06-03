from __future__ import annotations

from pydantic import Field

from src.webapp_studio.backend.contracts.contract_model import ContractModel
from src.webapp_studio.backend.contracts.private_thread_dto import PrivateThreadDto


class ActivitySnapshot(ContractModel):
    active_agent_ids: list[str] = Field(default_factory=list)
    private_threads: list[PrivateThreadDto] = Field(default_factory=list)
