from __future__ import annotations

from dataclasses import dataclass

from src.type_defs import JsonObject
from src.team_loader.models._coercion import as_json_object, optional_string, string_value


@dataclass(frozen=True)
class RelationDefinition:
    id: str
    source: str
    target: str
    relation: str
    tool_name: str | None
    input_schema: JsonObject
    description: str | None

    @classmethod
    def from_mapping(cls, value: object) -> RelationDefinition:
        mapping = as_json_object(value)
        return cls(
            id=optional_string(mapping.get("id")) or "",
            source=string_value(mapping.get("from")),
            target=string_value(mapping.get("to")),
            relation=string_value(mapping.get("relation")),
            tool_name=optional_string(mapping.get("tool_name")),
            input_schema=as_json_object(mapping.get("input_schema")),
            description=optional_string(mapping.get("description")),
        )
