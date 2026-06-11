from __future__ import annotations

from dataclasses import dataclass

from src.type_defs import JsonObject


@dataclass(frozen=True)
class LockedPackageTeam:
    raw: JsonObject

    @property
    def id(self) -> str:
        return str(self.raw.get("id") or "")

    @property
    def path(self) -> str:
        return str(self.raw.get("path") or "")
