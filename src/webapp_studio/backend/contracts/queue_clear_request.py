from __future__ import annotations

from typing import Literal

from src.webapp_studio.backend.contracts.contract_model import ContractModel


class QueueClearRequest(ContractModel):
    scope: Literal["failed", "pending", "all"] = "failed"
