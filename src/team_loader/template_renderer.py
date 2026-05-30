from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from .include_resolver import IncludeResolver


class TemplateRenderer:
    def __init__(self, include_resolver: IncludeResolver | None = None) -> None:
        self._include_resolver = include_resolver or IncludeResolver()

    def render(self, text: str, variables: dict[str, Any], base_path: Path) -> str:
        included = self._include_resolver.resolve(text, base_path)
        return self.render_variables(included, variables)

    def render_variables(self, text: str, variables: dict[str, Any]) -> str:
        pattern = re.compile(r"\{\{\s*([A-Za-z_][A-Za-z0-9_]*)\s*\}\}")
        rendered: list[str] = []
        cursor = 0
        for match in pattern.finditer(text):
            rendered.append(text[cursor:match.start()])
            rendered.append(self._render_variable_match(match, variables))
            cursor = match.end()
        rendered.append(text[cursor:])
        return "".join(rendered)

    def _render_variable_match(self, match: re.Match[str], variables: dict[str, Any]) -> str:
        key = match.group(1)
        if key not in variables:
            return match.group(0)
        value = variables[key]
        return "" if value is None else str(value)

    def render_config_value(self, value: Any, variables: dict[str, Any]) -> Any:
        if isinstance(value, str):
            return self.render_config_string(value, variables)
        if isinstance(value, list):
            return [self.render_config_value(item, variables) for item in value]
        if isinstance(value, dict):
            return {key: self.render_config_value(item, variables) for key, item in value.items()}
        return value

    def render_config_string(self, text: str, variables: dict[str, Any]) -> str:
        pattern = re.compile(r"\{([A-Za-z_][A-Za-z0-9_]*)\}")
        rendered: list[str] = []
        cursor = 0
        for match in pattern.finditer(text):
            rendered.append(text[cursor:match.start()])
            rendered.append(self._render_config_match(match, variables))
            cursor = match.end()
        rendered.append(text[cursor:])
        return "".join(rendered)

    def _render_config_match(self, match: re.Match[str], variables: dict[str, Any]) -> str:
        key = match.group(1)
        if key not in variables:
            return match.group(0)
        value = variables[key]
        return "" if value is None else str(value)
