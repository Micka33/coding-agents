from __future__ import annotations

from dataclasses import dataclass

from src.team_loader.models._coercion import as_json_object, string_tuple


@dataclass(frozen=True)
class HumanInputSettings:
    default_targets: tuple[str, ...] = ()

    @classmethod
    def from_mapping(cls, value: object) -> HumanInputSettings:
        mapping = as_json_object(value)
        return cls(default_targets=string_tuple(mapping.get("default_targets")))
