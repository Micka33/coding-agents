from __future__ import annotations

import os

from deepagents.backends import CompositeBackend, FilesystemBackend, LocalShellBackend

from src.team_loader.models.agent_definition import AgentDefinition
from src.team_loader.models.team_definition import TeamDefinition

from src.team_instanciator.resolvers.root_dir_resolver import RootDirResolver
from src.team_instanciator.configuration.runtime_configuration import RuntimeConfiguration


class BackendFactory:
    def __init__(self, configuration: RuntimeConfiguration | None = None) -> None:
        self._configuration = configuration or RuntimeConfiguration()
        self._root_dir_resolver = RootDirResolver()

    def create(self, team: TeamDefinition, agent: AgentDefinition) -> CompositeBackend | FilesystemBackend:
        root_dir = self._root_dir_resolver.resolve(team)
        filesystem = FilesystemBackend(root_dir=root_dir, virtual_mode=True)
        if self._execution_backend(team) == "local" and "shell" in agent.toolsets:
            shell = LocalShellBackend(root_dir=root_dir, virtual_mode=True, env={"PATH": os.environ.get("PATH", "")})
            return CompositeBackend(default=shell, routes={"/": filesystem})
        return filesystem

    def _execution_backend(self, team: TeamDefinition) -> str:
        env = team.defaults.execution_backend.env
        if env:
            configured = self._configuration.get(env)
            if configured:
                return str(configured)
        return team.defaults.execution_backend.default or "none"
