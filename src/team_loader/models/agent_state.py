from __future__ import annotations

from dataclasses import dataclass

from src.team_loader.models._coercion import as_json_object, string_value


@dataclass(frozen=True)
class AgentState:
    persistence: str

    @classmethod
    def from_mapping(cls, value: object) -> AgentState:
        mapping = as_json_object(value)
        return cls(persistence=string_value(mapping.get("persistence"), "inherit"))
