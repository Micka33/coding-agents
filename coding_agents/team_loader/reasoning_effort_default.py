from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class ReasoningEffortDefault:
    env: str | None
    default: str | None

    @classmethod
    def from_mapping(cls, value: Any) -> ReasoningEffortDefault:
        mapping = value if isinstance(value, dict) else {}
        return cls(env=mapping.get("env"), default=mapping.get("default"))
