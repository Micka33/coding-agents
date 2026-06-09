from __future__ import annotations

from pathlib import Path

from src.team_loader.models.agent_definition import AgentDefinition
from src.team_loader.models.team_definition import TeamDefinition


class WorkingDirectoryResolver:
    def resolve_launch_cwd(self, team: TeamDefinition) -> Path:
        return Path(getattr(team, "load_cwd", Path.cwd())).expanduser().resolve()

    def resolve_team(self, team: TeamDefinition) -> Path:
        configured = Path(str(getattr(team, "working_directory", "."))).expanduser()
        if configured.is_absolute():
            return configured.resolve()
        return (self.resolve_launch_cwd(team) / configured).resolve()

    def resolve_agent(self, team: TeamDefinition, agent: AgentDefinition) -> Path:
        configured = Path(str(getattr(agent, "relative_working_directory", ".")))
        if configured.is_absolute():
            raise ValueError("Agent relative_working_directory must be relative.")
        team_directory = self.resolve_team(team)
        agent_directory = (team_directory / configured).resolve()
        agent_directory.relative_to(team_directory)
        return agent_directory
