from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import TYPE_CHECKING

from deepagents.middleware.filesystem import (
    GLOB_TOOL_DESCRIPTION,
    GREP_TOOL_DESCRIPTION,
    GlobSchema,
    GrepSchema,
    LsSchema,
    LIST_FILES_TOOL_DESCRIPTION,
    READ_FILE_TOOL_DESCRIPTION,
    ReadFileSchema,
)
from langchain_core.tools import StructuredTool

from src.type_defs import JsonObject
from src.team_instanciator.tools.scoped_read_tool_adapter import _ScopedReadToolAdapter

if TYPE_CHECKING:
    from src.team_instanciator.tools.custom_tool_context import CustomToolContext


def create_scoped_read_tools(context: CustomToolContext, args: JsonObject) -> list[StructuredTool]:
    raw_directory = args.get("relative_working_directory", ".")
    custom_root = Path(str(raw_directory))
    if custom_root.is_absolute():
        raise ValueError("relative_working_directory must be relative.")
    scoped_root = (context.root_dir / custom_root).resolve()
    scoped_root.relative_to(context.root_dir.resolve())
    return ScopedReadToolsFactory().create(scoped_root)


class ScopedReadToolsFactory:
    def create(self, root_dir: str | Path) -> list[StructuredTool]:
        adapter = _ScopedReadToolAdapter(root_dir)
        return [
            self._tool(adapter.ls, name="ls", description=LIST_FILES_TOOL_DESCRIPTION, args_schema=LsSchema),
            self._tool(
                adapter.read_file,
                name="read_file",
                description=READ_FILE_TOOL_DESCRIPTION,
                args_schema=ReadFileSchema,
            ),
            self._tool(adapter.glob, name="glob", description=GLOB_TOOL_DESCRIPTION, args_schema=GlobSchema),
            self._tool(adapter.grep, name="grep", description=GREP_TOOL_DESCRIPTION, args_schema=GrepSchema),
        ]

    def _tool(
        self,
        func: Callable[..., str],
        *,
        name: str,
        description: str,
        args_schema: type[object],
    ) -> StructuredTool:
        return StructuredTool.from_function(
            func,
            name=name,
            description=description,
            infer_schema=False,
            args_schema=args_schema,
            handle_tool_error=self._handle_tool_error,
            handle_validation_error=self._handle_validation_error,
        )

    def _handle_tool_error(self, error: Exception) -> str:
        return self._tool_error(str(error))

    def _handle_validation_error(self, error: object) -> str:
        return self._tool_error(f"Invalid tool input: {error}")

    def _tool_error(self, message: str) -> str:
        return f"Error: {message}"


__all__ = ["ScopedReadToolsFactory", "_ScopedReadToolAdapter", "create_scoped_read_tools"]
