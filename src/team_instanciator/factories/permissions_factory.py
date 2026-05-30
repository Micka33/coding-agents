from __future__ import annotations

from deepagents.middleware.filesystem import FilesystemPermission

from src.team_loader.models.agent_definition import AgentDefinition


class PermissionsFactory:
    def create(self, agent: AgentDefinition) -> list[FilesystemPermission]:
        permissions: list[FilesystemPermission] = []
        if "scoped_read_tools" in agent.toolsets:
            permissions.append(FilesystemPermission(operations=["read"], paths=["/**"], mode="allow"))
        else:
            permissions.append(FilesystemPermission(operations=["read"], paths=["/**"], mode="deny"))
        if "write" in agent.toolsets:
            permissions.append(FilesystemPermission(operations=["write"], paths=["/**"], mode="allow"))
        else:
            permissions.append(FilesystemPermission(operations=["write"], paths=["/**"], mode="deny"))
        return permissions
