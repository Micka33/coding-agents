from __future__ import annotations

from pathlib import Path

from langchain_core.tools import BaseTool

from coding_agents.team_loader.custom_tool_definition import CustomToolDefinition

from .scoped_read_tools_factory import ScopedReadToolsFactory
from .team_instanciator_error import TeamInstanciatorError


class CustomToolFactory:
    def create(self, definition: CustomToolDefinition, root_dir: Path) -> list[BaseTool]:
        if definition.factory == "coding_agents.scout:scout_tools":
            tools = ScopedReadToolsFactory().create(self._root_dir(definition, root_dir))
            try:
                definition.validate_returned_tools(tuple(tool.name for tool in tools))
            except ValueError as error:
                raise TeamInstanciatorError(str(error)) from error
            return tools
        raise TeamInstanciatorError(f"Unsupported custom tool factory: {definition.factory}")

    def _root_dir(self, definition: CustomToolDefinition, root_dir: Path) -> Path:
        raw_root = definition.args.get("root_dir", root_dir)
        custom_root = Path(str(raw_root))
        if custom_root.is_absolute():
            return custom_root
        return (root_dir / custom_root).resolve()
