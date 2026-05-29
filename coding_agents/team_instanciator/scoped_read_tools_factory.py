from __future__ import annotations

import glob as glob_module
from collections.abc import Callable
from pathlib import Path
from typing import TYPE_CHECKING, Any

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
        self._root_dir = Path(root_dir).resolve()
        return [
            self._tool(self.ls, name="ls", description="List files under a directory."),
            self._tool(self.read_file, name="read_file", description="Read a text file."),
            self._tool(self.glob, name="glob", description="Find files by glob pattern."),
            self._tool(self.grep, name="grep", description="Search text files for a substring."),
        ]

    def ls(self, path: str = ".") -> list[str]:
        """List entries under a directory."""

        try:
            target = self._safe_path(path)
            if not target.exists():
                return [self._tool_error(f"Cannot list '{path}': path does not exist.")]
            if not target.is_dir():
                return [self._tool_error(f"Cannot list '{path}': path is not a directory.")]
            return sorted(entry.name for entry in target.iterdir())
        except Exception as exc:  # pragma: no cover - defensive tool boundary
            return [self._tool_error(f"Cannot list '{path}': {exc}")]

    def read_file(self, path: str, start_line: int = 1, end_line: int | None = None) -> str:
        """Read a text file, optionally with line bounds."""

        try:
            target = self._safe_path(path)
            if not target.exists():
                return self._tool_error(f"Cannot read '{path}': path does not exist.")
            if not target.is_file():
                return self._tool_error(f"Cannot read '{path}': path is not a file.")
            lines = target.read_text(encoding="utf-8", errors="replace").splitlines()
            start = max(start_line, 1) - 1
            end = end_line if end_line is not None else len(lines)
            return "\n".join(lines[start:end])
        except Exception as exc:  # pragma: no cover - defensive tool boundary
            return self._tool_error(f"Cannot read '{path}': {exc}")

    def glob(self, pattern: str) -> list[str]:
        """Return repository-relative paths matching a glob pattern."""

        try:
            clean_pattern = self._safe_pattern(pattern)
            matches = glob_module.glob(str(self._root_dir / clean_pattern), recursive=True)
            results: list[str] = []
            errors: list[str] = []
            for match in matches:
                try:
                    relative = self._relative_to_root(Path(match).resolve(), match)
                    results.append(str(relative))
                except Exception as exc:
                    errors.append(self._tool_error(f"Skipping glob match '{match}': {exc}"))
            return sorted(results) + sorted(errors)
        except Exception as exc:  # pragma: no cover - defensive tool boundary
            return [self._tool_error(f"Cannot glob '{pattern}': {exc}")]

    def grep(self, pattern: str, path: str = ".") -> list[str]:
        """Search files under path for a literal substring."""

        try:
            target = self._safe_path(path)
            if not target.exists():
                return [self._tool_error(f"Cannot search '{path}': path does not exist.")]
            if not target.is_dir() and not target.is_file():
                return [self._tool_error(f"Cannot search '{path}': path is not a file or directory.")]
            files = target.rglob("*") if target.is_dir() else [target]
            results: list[str] = []
            errors: list[str] = []
            for file_path in files:
                try:
                    if file_path.is_file():
                        self._grep_file(file_path, pattern, results, errors)
                except Exception as exc:
                    errors.append(self._tool_error(f"Skipping grep target '{file_path}': {exc}"))
            return results + errors
        except Exception as exc:  # pragma: no cover - defensive tool boundary
            return [self._tool_error(f"Cannot search '{path}': {exc}")]

    def _grep_file(self, file_path: Path, pattern: str, results: list[str], errors: list[str]) -> None:
        try:
            relative = self._relative_to_root(file_path.resolve(), str(file_path))
            lines = file_path.read_text(encoding="utf-8", errors="replace").splitlines()
            for number, line in enumerate(lines, 1):
                if pattern in line:
                    results.append(f"{relative}:{number}:{line}")
        except UnicodeDecodeError:
            return
        except OSError as exc:
            errors.append(self._tool_error(f"Cannot read grep target '{file_path}': {exc}"))

    def _safe_pattern(self, pattern: str) -> str:
        clean_pattern = pattern.lstrip("/") or "."
        if ".." in Path(clean_pattern).parts:
            raise PermissionError(f"Path traversal is not allowed in glob pattern: {pattern}")
        return clean_pattern

    def _safe_path(self, path: str) -> Path:
        clean_path = path.lstrip("/") or "."
        target = (self._root_dir / clean_path).resolve()
        self._relative_to_root(target, path)
        return target

    def _relative_to_root(self, target: Path, requested_path: str) -> Path:
        try:
            return target.relative_to(self._root_dir)
        except ValueError as exc:
            raise PermissionError(f"Path is outside root: {requested_path}") from exc

    def _tool(self, func: Callable[..., Any], *, name: str, description: str) -> StructuredTool:
        return StructuredTool.from_function(
            func,
            name=name,
            description=description,
            handle_tool_error=self._handle_tool_error,
            handle_validation_error=self._handle_validation_error,
        )

    def _handle_tool_error(self, error: Exception) -> str:
        return self._tool_error(str(error))

    def _handle_validation_error(self, error: Any) -> str:
        return self._tool_error(f"Invalid tool input: {error}")

    def _tool_error(self, message: str) -> str:
        return f"Error: {message}"
