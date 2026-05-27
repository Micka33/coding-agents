from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class RelationDefinition:
    source: str
    target: str
    relation: str
    tool_name: str | None
    input_schema: dict[str, Any]
    description: str | None

    @classmethod
    def from_mapping(cls, value: Any) -> RelationDefinition:
        mapping = value if isinstance(value, dict) else {}
        return cls(
            source=mapping.get("from", ""),
            target=mapping.get("to", ""),
            relation=mapping.get("relation", ""),
            tool_name=mapping.get("tool_name"),
            input_schema=dict(mapping.get("input_schema", {}) if isinstance(mapping.get("input_schema"), dict) else {}),
            description=mapping.get("description"),
        )
