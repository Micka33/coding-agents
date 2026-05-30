from __future__ import annotations

from dataclasses import dataclass

from src.team_loader.models._coercion import as_json_object

from src.team_loader.errors.team_loader_error import TeamLoaderError


@dataclass(frozen=True)
class ToolReference:
    name: str | None = None
    custom: str | None = None

    @classmethod
    def from_value(cls, value: object) -> ToolReference:
        if isinstance(value, str):
            return cls(name=value)
        mapping = as_json_object(value)
        if set(mapping) == {"custom"} and isinstance(mapping["custom"], str):
            return cls(custom=mapping["custom"])
        raise TeamLoaderError(f"Invalid tool reference: {value!r}")
