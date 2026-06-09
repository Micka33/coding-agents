from __future__ import annotations

from src.team_instanciator.errors.team_instanciator_error import TeamInstanciatorError


class ToolNameValidator:
    def validate_unique(self, owner: str, tools: list[object]) -> None:
        seen: set[str] = set()
        duplicates: set[str] = set()
        for tool in tools:
            name = getattr(tool, "name", None)
            if not isinstance(name, str):
                continue
            if name in seen:
                duplicates.add(name)
            seen.add(name)
        if duplicates:
            names = ", ".join(sorted(duplicates))
            raise TeamInstanciatorError(f"Agent '{owner}' has duplicate tool names: {names}.")
