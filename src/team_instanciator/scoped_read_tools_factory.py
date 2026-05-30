from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import TYPE_CHECKING, Any, Literal

from deepagents.backends import FilesystemBackend
from deepagents.backends.protocol import ReadResult
from deepagents.backends.utils import (
    _get_file_type,
    check_empty_content,
    format_content_with_line_numbers,
    format_grep_matches,
    truncate_if_too_long,
    validate_path,
)
from deepagents.middleware.filesystem import (
    DEFAULT_READ_LIMIT,
    DEFAULT_READ_OFFSET,
    GLOB_TOOL_DESCRIPTION,
    GREP_TOOL_DESCRIPTION,
    GlobSchema,
    GrepSchema,
    LsSchema,
    LIST_FILES_TOOL_DESCRIPTION,
    NUM_CHARS_PER_TOKEN,
    READ_FILE_TOOL_DESCRIPTION,
    READ_FILE_TRUNCATION_MSG,
    ReadFileSchema,
)
from langchain_core.tools import StructuredTool

if TYPE_CHECKING:
    from .custom_tool_context import CustomToolContext


def create_scoped_read_tools(context: CustomToolContext, args: dict[str, Any]) -> list[StructuredTool]:
    raw_root = args.get("root_dir", context.root_dir)
    custom_root = Path(str(raw_root))
    if not custom_root.is_absolute():
        custom_root = (context.root_dir / custom_root).resolve()
    return ScopedReadToolsFactory().create(custom_root)


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
        func: Callable[..., Any],
        *,
        name: str,
        description: str,
        args_schema: type[Any],
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

    def _handle_validation_error(self, error: Any) -> str:
        return self._tool_error(f"Invalid tool input: {error}")

    def _tool_error(self, message: str) -> str:
        return f"Error: {message}"


class _ScopedReadToolAdapter:
    def __init__(self, root_dir: str | Path, *, tool_token_limit: int | None = 20_000) -> None:
        self._backend = FilesystemBackend(root_dir=Path(root_dir).resolve(), virtual_mode=True)
        self._tool_token_limit = tool_token_limit

    def ls(self, path: str) -> str:
        """List entries under a directory using Deep Agents filesystem semantics."""

        try:
            validated_path = validate_path(path)
            result = self._backend.ls(validated_path)
            if result.error:
                return f"Error: {result.error}"
            paths = [entry.get("path", "") for entry in result.entries or []]
            return str(truncate_if_too_long(paths))
        except Exception as exc:  # pragma: no cover - defensive tool boundary
            return f"Error: {exc}"

    def read_file(
        self,
        file_path: str,
        offset: int = DEFAULT_READ_OFFSET,
        limit: int = DEFAULT_READ_LIMIT,
    ) -> str:
        """Read a file using Deep Agents filesystem semantics."""

        try:
            validated_path = validate_path(file_path)
            return self._format_read_result(
                self._backend.read(validated_path, offset=offset, limit=limit),
                validated_path,
                offset,
                limit,
            )
        except Exception as exc:  # pragma: no cover - defensive tool boundary
            return f"Error: {exc}"

    def glob(self, pattern: str, path: str = "/") -> str:
        """Find files by glob pattern using Deep Agents filesystem semantics."""

        try:
            validated_path = validate_path(path)
            result = self._backend.glob(pattern, path=validated_path)
            if result.error:
                return f"Error: {result.error}"
            paths = [entry.get("path", "") for entry in result.matches or []]
            return str(truncate_if_too_long(paths))
        except Exception as exc:  # pragma: no cover - defensive tool boundary
            return f"Error: {exc}"

    def grep(
        self,
        pattern: str,
        path: str | None = None,
        glob: str | None = None,
        output_mode: Literal["files_with_matches", "content", "count"] = "files_with_matches",
    ) -> str:
        """Search files using Deep Agents filesystem semantics."""

        try:
            validated_path = validate_path(path) if path is not None else None
            result = self._backend.grep(pattern, path=validated_path, glob=glob)
            if result.error:
                return result.error
            formatted = format_grep_matches(result.matches or [], output_mode)
            truncated = truncate_if_too_long(formatted)
            return str(truncated)
        except Exception as exc:  # pragma: no cover - defensive tool boundary
            return f"Error: {exc}"

    def _format_read_result(self, result: ReadResult, validated_path: str, offset: int, limit: int) -> str:
        if result.error:
            return f"Error: {result.error}"
        if result.file_data is None:
            return f"Error: no data returned for '{validated_path}'"

        content = result.file_data["content"]
        if _get_file_type(validated_path) != "text":
            return content

        empty_msg = check_empty_content(content)
        if empty_msg:
            return empty_msg

        formatted = format_content_with_line_numbers(content, start_line=offset + 1)
        return self._truncate_read_content(formatted, validated_path, limit)

    def _truncate_read_content(self, content: str, file_path: str, limit: int) -> str:
        lines = content.splitlines(keepends=True)
        if len(lines) > limit:
            lines = lines[:limit]
            content = "".join(lines)

        if self._tool_token_limit and len(content) >= NUM_CHARS_PER_TOKEN * self._tool_token_limit:
            truncation_msg = READ_FILE_TRUNCATION_MSG.format(file_path=file_path)
            max_content_length = NUM_CHARS_PER_TOKEN * self._tool_token_limit - len(truncation_msg)
            content = content[:max_content_length] + truncation_msg

        return content
