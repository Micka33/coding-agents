from __future__ import annotations

import glob as glob_module
from pathlib import Path

from langchain_core.tools import StructuredTool


class ScopedReadToolsFactory:
    def create(self, root_dir: str | Path) -> list[StructuredTool]:
        self._root_dir = Path(root_dir).resolve()
        return [
            StructuredTool.from_function(self.ls, name="ls", description="List files under a directory."),
            StructuredTool.from_function(self.read_file, name="read_file", description="Read a text file."),
            StructuredTool.from_function(self.glob, name="glob", description="Find files by glob pattern."),
            StructuredTool.from_function(self.grep, name="grep", description="Search text files for a substring."),
        ]

    def ls(self, path: str = ".") -> list[str]:
        """List entries under a directory."""

        target = self._safe_path(path)
        return sorted(entry.name for entry in target.iterdir())

    def read_file(self, path: str, start_line: int = 1, end_line: int | None = None) -> str:
        """Read a text file, optionally with line bounds."""

        lines = self._safe_path(path).read_text(encoding="utf-8", errors="replace").splitlines()
        start = max(start_line, 1) - 1
        end = end_line if end_line is not None else len(lines)
        return "\n".join(lines[start:end])

    def glob(self, pattern: str) -> list[str]:
        """Return repository-relative paths matching a glob pattern."""

        matches = glob_module.glob(str(self._root_dir / pattern), recursive=True)
        return sorted(str(Path(match).resolve().relative_to(self._root_dir)) for match in matches)

    def grep(self, pattern: str, path: str = ".") -> list[str]:
        """Search files under path for a literal substring."""

        target = self._safe_path(path)
        files = target.rglob("*") if target.is_dir() else [target]
        results: list[str] = []
        for file_path in files:
            if file_path.is_file():
                self._grep_file(file_path, pattern, results)
        return results

    def _grep_file(self, file_path: Path, pattern: str, results: list[str]) -> None:
        try:
            for number, line in enumerate(file_path.read_text(encoding="utf-8").splitlines(), 1):
                if pattern in line:
                    relative = file_path.relative_to(self._root_dir)
                    results.append(f"{relative}:{number}:{line}")
        except UnicodeDecodeError:
            return

    def _safe_path(self, path: str) -> Path:
        target = (self._root_dir / path.lstrip("/")).resolve()
        target.relative_to(self._root_dir)
        return target
