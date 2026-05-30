from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .team_loader_error import TeamLoaderError


@dataclass(frozen=True)
class ToolReference:
    name: str | None = None
    custom: str | None = None

    @classmethod
    def from_value(cls, value: Any) -> ToolReference:
        if isinstance(value, str):
            return cls(name=value)
        if isinstance(value, dict) and set(value) == {"custom"} and isinstance(value["custom"], str):
            return cls(custom=value["custom"])
        raise TeamLoaderError(f"Invalid tool reference: {value!r}")
