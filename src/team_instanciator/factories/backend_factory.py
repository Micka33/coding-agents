from __future__ import annotations

import os

from deepagents.backends import CompositeBackend, FilesystemBackend, LocalShellBackend

from src.team_loader.models.agent_definition import AgentDefinition
from src.team_loader.models.team_definition import TeamDefinition
from src.team_loader.resolvers.working_directory_resolver import WorkingDirectoryResolver

from src.team_instanciator.backends.skill_filtering_backend import SkillFilteringBackend
from src.team_instanciator.configuration.runtime_configuration import RuntimeConfiguration
from src.team_instanciator.resolvers.resolved_skill_source import ResolvedSkillSource
from src.team_instanciator.resolvers.skill_source_resolver import SkillSourceResolver


class BackendFactory:
    def __init__(
        self,
        configuration: RuntimeConfiguration | None = None,
        skill_source_resolver: SkillSourceResolver | None = None,
    ) -> None:
        self._configuration = configuration or RuntimeConfiguration()
        self._working_directory_resolver = WorkingDirectoryResolver()
        self._skill_source_resolver = skill_source_resolver or SkillSourceResolver(self._configuration)

    def create(self, team: TeamDefinition, agent: AgentDefinition) -> CompositeBackend | FilesystemBackend:
        root_dir = self._working_directory_resolver.resolve_agent(team, agent)
        filesystem = FilesystemBackend(root_dir=root_dir, virtual_mode=True)
        skill_routes = self._skill_routes(team)
        if self._execution_backend(team) == "local" and "shell" in agent.toolsets:
            shell = LocalShellBackend(root_dir=root_dir, virtual_mode=True, env={"PATH": os.environ.get("PATH", "")})
            return CompositeBackend(default=shell, routes={"/": filesystem, **skill_routes})
        if skill_routes:
            return CompositeBackend(default=filesystem, routes=skill_routes)
        return filesystem

    def _skill_routes(self, team: TeamDefinition) -> dict[str, object]:
        routes: dict[str, object] = {}
        for agent in team.agents.values():
            for source in self._skill_source_resolver.resolve_agent_sources(team, agent):
                routes[f"{source.virtual_path}/"] = self._backend_for_source(source)
        return routes

    def _backend_for_source(self, source: ResolvedSkillSource) -> object:
        backend = FilesystemBackend(root_dir=source.host_path, virtual_mode=True)
        if source.allowed_skill_ids is None:
            return backend
        return SkillFilteringBackend(backend, source.allowed_skill_ids)

    def _execution_backend(self, team: TeamDefinition) -> str:
        env = team.defaults.execution_backend.env
        if env:
            configured = self._configuration.get(env)
            if configured:
                return str(configured)
        return team.defaults.execution_backend.default or "none"
