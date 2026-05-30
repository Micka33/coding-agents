from __future__ import annotations

from dataclasses import dataclass
from typing import TypedDict

from src.team_instanciator.runtime.runtime_lane import RuntimeLane, RuntimeLaneDict


class TeamRuntimeManifestDict(TypedDict):
    team_id: str
    manifest_version: int
    lanes: list[RuntimeLaneDict]


@dataclass(frozen=True)
class TeamRuntimeManifest:
    team_id: str
    manifest_version: int
    lanes: tuple[RuntimeLane, ...]

    def lanes_for(self, parent_thread_id: str) -> list[RuntimeLaneDict]:
        return [lane.to_dict(parent_thread_id) for lane in self.lanes]

    def to_dict(self) -> TeamRuntimeManifestDict:
        return {
            "team_id": self.team_id,
            "manifest_version": self.manifest_version,
            "lanes": [lane.to_dict() for lane in self.lanes],
        }
