from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .runtime_lane import RuntimeLane


@dataclass(frozen=True)
class TeamRuntimeManifest:
    team_id: str
    manifest_version: int
    lanes: tuple[RuntimeLane, ...]

    def lanes_for(self, parent_thread_id: str) -> list[dict[str, Any]]:
        return [lane.to_dict(parent_thread_id) for lane in self.lanes]

    def to_dict(self) -> dict[str, Any]:
        return {
            "team_id": self.team_id,
            "manifest_version": self.manifest_version,
            "lanes": [lane.to_dict() for lane in self.lanes],
        }
