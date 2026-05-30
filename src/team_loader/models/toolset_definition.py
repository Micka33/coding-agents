from __future__ import annotations

from dataclasses import dataclass

from src.team_loader.models.tool_reference import ToolReference


@dataclass(frozen=True)
class ToolsetDefinition:
    name: str
    tools: tuple[ToolReference, ...]

    @classmethod
    def from_sequence(cls, name: str, value: object) -> ToolsetDefinition:
        sequence = value if isinstance(value, list) else []
        return cls(name=name, tools=tuple(ToolReference.from_value(item) for item in sequence))
