from __future__ import annotations

from dataclasses import dataclass

from src.team_loader.models._coercion import as_json_object, string_tuple


@dataclass(frozen=True)
class MemoryDefault:
    error_when_missing: bool
    candidates: tuple[str, ...]

    @classmethod
    def from_mapping(cls, value: object) -> MemoryDefault:
        mapping = as_json_object(value)
        return cls(
            error_when_missing=bool(mapping.get("error_when_missing", False)),
            candidates=string_tuple(mapping.get("candidates")),
        )
