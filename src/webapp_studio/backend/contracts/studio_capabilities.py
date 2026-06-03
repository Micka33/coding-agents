from __future__ import annotations

from src.webapp_studio.backend.contracts.contract_model import ContractModel
from src.webapp_studio.backend.contracts.types import CapabilityStatus


class StudioCapabilities(ContractModel):
    streaming: CapabilityStatus = "available"
    queue_control: CapabilityStatus = "degraded"
    interrupts: CapabilityStatus = "degraded"
    checkpoints: CapabilityStatus = "degraded"
    branching: CapabilityStatus = "degraded"
    time_travel: CapabilityStatus = "degraded"
    generated_ui: CapabilityStatus = "degraded"
