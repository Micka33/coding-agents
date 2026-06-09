from __future__ import annotations

from deepagents.middleware.filesystem import FilesystemPermission

from src.team_loader.models.agent_definition import AgentDefinition
from src.team_loader.models.team_definition import TeamDefinition
from src.team_instanciator.resolvers.skill_source_resolver import SkillSourceResolver


class PermissionsFactory:
    def __init__(self, skill_source_resolver: SkillSourceResolver | None = None) -> None:
        self._skill_source_resolver = skill_source_resolver or SkillSourceResolver()

    def create(self, agent: AgentDefinition, team: TeamDefinition | None = None) -> list[FilesystemPermission]:
        permissions: list[FilesystemPermission] = []
        if "scoped_read_tools" in agent.toolsets:
            permissions.append(FilesystemPermission(operations=["read"], paths=["/**"], mode="allow"))
        else:
            skill_paths = self._skill_read_paths(team, agent)
            if skill_paths:
                permissions.append(FilesystemPermission(operations=["read"], paths=skill_paths, mode="allow"))
            permissions.append(FilesystemPermission(operations=["read"], paths=["/**"], mode="deny"))
        if "write" in agent.toolsets:
            permissions.append(FilesystemPermission(operations=["write"], paths=["/**"], mode="allow"))
        else:
            permissions.append(FilesystemPermission(operations=["write"], paths=["/**"], mode="deny"))
        return permissions

    def _skill_read_paths(self, team: TeamDefinition | None, agent: AgentDefinition) -> list[str]:
        if team is None:
            return []
        return self._skill_source_resolver.read_permission_paths(team, agent)
