from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from coding_agents.team_loader.team_definition import TeamDefinition

from .checkpointer_handle import CheckpointerHandle
from .team_runtime_manifest import TeamRuntimeManifest


@dataclass
class InstantiatedTeam:
    team: TeamDefinition
    graph: Any
    checkpointer_handle: CheckpointerHandle
    runtime_manifest: TeamRuntimeManifest

    def invoke(self, *args: Any, **kwargs: Any) -> Any:
        return self.graph.invoke(*args, **kwargs)

    def close(self) -> None:
        self.checkpointer_handle.close()

    def __enter__(self) -> InstantiatedTeam:
        return self

    def __exit__(self, exc_type: Any, exc: Any, tb: Any) -> None:
        self.close()

    def __getattr__(self, name: str) -> Any:
        return getattr(self.graph, name)
