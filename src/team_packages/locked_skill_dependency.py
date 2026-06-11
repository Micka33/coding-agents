from __future__ import annotations

from dataclasses import dataclass

from src.type_defs import JsonObject


@dataclass(frozen=True)
class LockedSkillDependency:
    raw: JsonObject

    @property
    def id(self) -> str:
        return str(self.raw.get("id") or "")

    @property
    def resolved(self) -> str:
        return str(self.raw.get("resolved") or "")

    @property
    def installed_path_value(self) -> object:
        return self.raw.get("installed_path")
