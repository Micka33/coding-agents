from __future__ import annotations

import os
from pathlib import Path

from src.team_loader.models.agent_definition import AgentDefinition
from src.team_loader.models.team_definition import TeamDefinition
from src.team_loader.resolvers.working_directory_resolver import WorkingDirectoryResolver

from src.team_instanciator.configuration.runtime_configuration import RuntimeConfiguration


class SkillsResolver:
    def __init__(self, configuration: RuntimeConfiguration | None = None) -> None:
        self._configuration = configuration or RuntimeConfiguration()
        self._working_directory_resolver = WorkingDirectoryResolver()

    def resolve(self, team: TeamDefinition, agent: AgentDefinition) -> list[str] | None:
        if agent.skills is None or agent.skills == "inherit":
            return None
        if agent.skills == "none":
            return None
        if not isinstance(agent.skills, list):
            return None
        return [str(self._skill_path(team, skill_id)) for skill_id in agent.skills if isinstance(skill_id, str)]

    def _skill_path(self, team: TeamDefinition, skill_id: str) -> Path:
        project_path = self._project_skills_dir(team) / skill_id
        if (project_path / "SKILL.md").is_file():
            return project_path
        home = self._configuration.get("CODEX_HOME") or os.environ.get("CODEX_HOME")
        if home:
            user_path = Path(home) / "skills" / skill_id
            if (user_path / "SKILL.md").is_file():
                return user_path
        return project_path

    def _project_skills_dir(self, team: TeamDefinition) -> Path:
        return self._working_directory_resolver.resolve_launch_cwd(team) / ".agents" / "skills"
