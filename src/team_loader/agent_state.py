from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class AgentState:
    persistence: str

    @classmethod
    def from_mapping(cls, value: Any) -> AgentState:
        mapping = value if isinstance(value, dict) else {}
        return cls(persistence=mapping.get("persistence", "inherit"))
