from __future__ import annotations

from src.team_loader.models.agent_definition import AgentDefinition
from src.team_loader.models.team_definition import TeamDefinition
from src.team_instanciator.configuration.runtime_configuration import RuntimeConfiguration
from src.team_instanciator.tools.deep_agent_tool_visibility_middleware import DeepAgentToolVisibilityMiddleware


class ToolVisibilityFactory:
    READ_TOOLS = frozenset({"ls", "read_file", "glob", "grep"})
    WRITE_TOOLS = frozenset({"write_file", "edit_file"})
    SHELL_TOOLS = frozenset({"execute"})
    DELEGATION_TOOLS = frozenset({"task"})
    DEEPAGENTS_BUILTIN_TOOLS = READ_TOOLS | WRITE_TOOLS | SHELL_TOOLS | DELEGATION_TOOLS

    def __init__(self, configuration: RuntimeConfiguration | None = None) -> None:
        self._configuration = configuration or RuntimeConfiguration()

    def create(
        self,
        team: TeamDefinition,
        agent: AgentDefinition,
        *,
        task_available: bool,
    ) -> DeepAgentToolVisibilityMiddleware:
        return DeepAgentToolVisibilityMiddleware(
            excluded_tools=self.excluded_tools(team, agent, task_available=task_available)
        )

    def excluded_tools(
        self,
        team: TeamDefinition,
        agent: AgentDefinition,
        *,
        task_available: bool,
    ) -> frozenset[str]:
        excluded: set[str] = set()
        toolsets = set(agent.toolsets)
        if "scoped_read_tools" not in toolsets:
            excluded.update(self.READ_TOOLS)
        if "write" not in toolsets:
            excluded.update(self.WRITE_TOOLS)
        if "shell" not in toolsets or self._execution_backend(team) != "local":
            excluded.update(self.SHELL_TOOLS)
        if not task_available:
            excluded.update(self.DELEGATION_TOOLS)
        return frozenset(excluded)

    def _execution_backend(self, team: TeamDefinition) -> str:
        env = team.defaults.execution_backend.env
        if env:
            configured = self._configuration.get(env)
            if configured:
                return str(configured)
        return team.defaults.execution_backend.default or "none"
