from __future__ import annotations

from src.webapp_studio.backend.contracts.contract_model import ContractModel
from src.webapp_studio.backend.contracts.types import CapabilityStatus


class CheckpointActionCapabilities(ContractModel):
    inspect: CapabilityStatus = "available"
    resume: CapabilityStatus = "unsupported"
    branch_from_here: CapabilityStatus = "unsupported"
