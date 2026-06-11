from __future__ import annotations

from src.team_loader.models.team_definition import TeamDefinition


class PackageRiskScanner:
    def risk_flags(self, team: TeamDefinition) -> tuple[str, ...]:
        flags: list[str] = []
        if team.custom_tools:
            flags.append("custom_tools")
        if any(server.transport == "stdio" for server in team.mcp_servers.values()):
            flags.append("stdio_mcp")
        if any(server.transport in {"streamable_http", "sse"} for server in team.mcp_servers.values()):
            flags.append("remote_mcp")
        if self._shell_can_resolve_to_local(team):
            flags.append("shell")
        return tuple(flags)

    def _shell_can_resolve_to_local(self, team: TeamDefinition) -> bool:
        if self._referenced_toolsets_expose_execute(team):
            return True
        if not any("shell" in agent.toolsets for agent in team.agents.values()):
            return False
        execution_backend = team.defaults.execution_backend
        return execution_backend.default == "local" or execution_backend.env is not None

    def _referenced_toolsets_expose_execute(self, team: TeamDefinition) -> bool:
        referenced_names = {name for agent in team.agents.values() for name in agent.toolsets}
        referenced = (team.toolsets[name] for name in referenced_names if name in team.toolsets)
        return any(tool.name == "execute" for toolset in referenced for tool in toolset.tools)
