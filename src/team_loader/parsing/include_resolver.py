from __future__ import annotations

import re
from pathlib import Path

from src.team_loader.errors.team_loader_error import TeamLoaderError


class IncludeResolver:
    def resolve(self, text: str, base_path: Path) -> str:
        return self._resolve(text, base_path, [])

    def _resolve(self, text: str, base_path: Path, stack: list[Path]) -> str:
        pattern = re.compile(r"\{\{\s*include:([^}]+?)\s*\}\}")
        resolved: list[str] = []
        cursor = 0
        for match in pattern.finditer(text):
            resolved.append(text[cursor:match.start()])
            resolved.append(self._resolve_match(match, base_path, stack))
            cursor = match.end()
        resolved.append(text[cursor:])
        return "".join(resolved)

    def _resolve_match(self, match: re.Match[str], base_path: Path, stack: list[Path]) -> str:
        raw_path = match.group(1).strip()
        include_path = (base_path.parent / raw_path).resolve()
        if include_path in stack:
            chain = " -> ".join(str(path) for path in [*stack, include_path])
            raise TeamLoaderError(f"Recursive include detected: {chain}")
        if not include_path.is_file():
            raise TeamLoaderError(f"Included prompt fragment does not exist: {include_path}")
        included = include_path.read_text(encoding="utf-8")
        return self._resolve(included, include_path, [*stack, include_path])
