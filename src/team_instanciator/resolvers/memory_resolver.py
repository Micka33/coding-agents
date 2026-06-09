from __future__ import annotations

from pathlib import Path

from src.team_loader.models.agent_definition import AgentDefinition
from src.team_loader.models.team_definition import TeamDefinition
from src.team_loader.resolvers.working_directory_resolver import WorkingDirectoryResolver

from src.team_instanciator.errors.team_instanciator_error import TeamInstanciatorError


class MemoryResolver:
    def __init__(self) -> None:
        self._working_directory_resolver = WorkingDirectoryResolver()

    def resolve(self, team: TeamDefinition, agent: AgentDefinition) -> list[str] | None:
        if agent.memory == "none":
            return None
        if isinstance(agent.memory, list):
            return self._validated(team, agent, tuple(agent.memory), True)
        return self._validated(team, agent, team.defaults.memory.candidates, team.defaults.memory.error_when_missing)

    def _validated(
        self,
        team: TeamDefinition,
        agent: AgentDefinition,
        candidates: tuple[object, ...],
        error_when_missing: bool,
    ) -> list[str]:
        result: list[str] = []
        for candidate in candidates:
            if not isinstance(candidate, str):
                continue
            path = self._real_path(team, agent, candidate)
            if path.exists():
                result.append(candidate)
            elif error_when_missing:
                raise TeamInstanciatorError(f"Memory file does not exist: {candidate}")
        return result or None

    def _real_path(self, team: TeamDefinition, agent: AgentDefinition, candidate: str) -> Path:
        relative = candidate.lstrip("/")
        return (self._working_directory_resolver.resolve_agent(team, agent) / relative).resolve()
