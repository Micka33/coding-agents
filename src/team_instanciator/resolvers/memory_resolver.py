from __future__ import annotations

from pathlib import Path

from src.team_loader.models.agent_definition import AgentDefinition
from src.team_loader.models.team_definition import TeamDefinition

from src.team_instanciator.resolvers.root_dir_resolver import RootDirResolver
from src.team_instanciator.errors.team_instanciator_error import TeamInstanciatorError


class MemoryResolver:
    def __init__(self) -> None:
        self._root_dir_resolver = RootDirResolver()

    def resolve(self, team: TeamDefinition, agent: AgentDefinition) -> list[str] | None:
        if agent.memory == "none":
            return None
        if isinstance(agent.memory, list):
            return self._validated(team, tuple(agent.memory), True)
        return self._validated(team, team.defaults.memory.candidates, team.defaults.memory.error_when_missing)

    def _validated(self, team: TeamDefinition, candidates: tuple[object, ...], error_when_missing: bool) -> list[str]:
        result: list[str] = []
        for candidate in candidates:
            if not isinstance(candidate, str):
                continue
            path = self._real_path(team, candidate)
            if path.exists():
                result.append(candidate)
            elif error_when_missing:
                raise TeamInstanciatorError(f"Memory file does not exist: {candidate}")
        return result or None

    def _real_path(self, team: TeamDefinition, candidate: str) -> Path:
        relative = candidate.lstrip("/")
        return (self._root_dir_resolver.resolve(team) / relative).resolve()
