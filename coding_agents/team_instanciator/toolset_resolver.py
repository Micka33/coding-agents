from __future__ import annotations

from pathlib import Path

from langchain_core.tools import BaseTool

from coding_agents.team_loader.agent_definition import AgentDefinition
from coding_agents.team_loader.team_definition import TeamDefinition

from .builtin_tool_factory import BuiltinToolFactory
from .custom_tool_factory import CustomToolFactory
from .root_dir_resolver import RootDirResolver
from .runtime_configuration import RuntimeConfiguration


class ToolsetResolver:
    _DEEPAGENTS_BUILTIN_TOOL_NAMES = frozenset(
        {"ls", "read_file", "glob", "grep", "write_file", "edit_file", "execute"}
    )
    _SELF_CONTAINED_TOOL_NAMES = frozenset({"web_search", "fetch_url"})

    def __init__(self, configuration: RuntimeConfiguration | None = None) -> None:
        self._builtin_factory = BuiltinToolFactory(configuration)
        self._custom_factory = CustomToolFactory()
        self._root_dir_resolver = RootDirResolver()

    def resolve_for_langchain(self, team: TeamDefinition, agent: AgentDefinition) -> list[BaseTool]:
        return self._resolve(team, agent, include_deepagents_builtin=True)

    def resolve_for_deepagents(self, team: TeamDefinition, agent: AgentDefinition) -> list[BaseTool]:
        return self._resolve(team, agent, include_deepagents_builtin=False)

    def _resolve(self, team: TeamDefinition, agent: AgentDefinition, include_deepagents_builtin: bool) -> list[BaseTool]:
        tools: list[BaseTool] = []
        root_dir = self._root_dir(team)
        for toolset_name in agent.toolsets:
            toolset = team.toolsets[toolset_name]
            for reference in toolset.tools:
                if reference.custom:
                    custom_tools = self._custom_factory.create(team.custom_tools[reference.custom], root_dir)
                    tools.extend(
                        tool
                        for tool in custom_tools
                        if self._should_include_resolved_tool(tool.name, include_deepagents_builtin)
                    )
                elif reference.name and self._should_include_reference(reference.name, include_deepagents_builtin):
                    tools.append(self._builtin_factory.create(reference.name, root_dir))
        return tools

    def _should_include_reference(self, name: str, include_deepagents_builtin: bool) -> bool:
        if include_deepagents_builtin:
            return True
        return name in self._SELF_CONTAINED_TOOL_NAMES

    def _should_include_resolved_tool(self, name: str, include_deepagents_builtin: bool) -> bool:
        if include_deepagents_builtin:
            return True
        return name not in self._DEEPAGENTS_BUILTIN_TOOL_NAMES

    def _root_dir(self, team: TeamDefinition) -> Path:
        return self._root_dir_resolver.resolve(team)
