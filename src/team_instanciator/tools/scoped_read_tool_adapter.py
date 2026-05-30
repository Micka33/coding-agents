from __future__ import annotations

from pathlib import Path
from typing import Literal

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
    NUM_CHARS_PER_TOKEN,
    READ_FILE_TRUNCATION_MSG,
)


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
