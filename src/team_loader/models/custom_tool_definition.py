from __future__ import annotations

from dataclasses import dataclass

from src.type_defs import JsonObject
from src.team_loader.models._coercion import as_json_object, string_tuple, string_value

@dataclass(frozen=True)
class CustomToolDefinition:
    id: str
    factory: str
    args: JsonObject
    exposes: tuple[str, ...]

    @classmethod
    def from_mapping(cls, custom_id: str, value: object) -> CustomToolDefinition:
        mapping = as_json_object(value)
        return cls(
            id=custom_id,
            factory=string_value(mapping.get("factory")),
            args=as_json_object(mapping.get("args")),
            exposes=string_tuple(mapping.get("exposes")),
        )

    def validate_returned_tools(self, tool_names: list[str] | tuple[str, ...]) -> None:
        expected = set(self.exposes)
        actual = set(tool_names)
        if expected != actual:
            missing = sorted(expected - actual)
            extra = sorted(actual - expected)
            details = []
            if missing:
                details.append(f"missing: {', '.join(missing)}")
            if extra:
                details.append(f"extra: {', '.join(extra)}")
            raise ValueError(f"Custom tool '{self.id}' exposes mismatch ({'; '.join(details)}).")
