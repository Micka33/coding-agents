from __future__ import annotations

from dataclasses import dataclass

from src.team_loader.models._coercion import as_json_object, optional_string


@dataclass(frozen=True)
class ModelDefault:
    env: str | None
    default: str | None

    @classmethod
    def from_mapping(cls, value: object) -> ModelDefault:
        mapping = as_json_object(value)
        return cls(env=optional_string(mapping.get("env")), default=optional_string(mapping.get("default")))
