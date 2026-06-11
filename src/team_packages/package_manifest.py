from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from src.type_defs import JsonObject, is_json_object


@dataclass(frozen=True)
class PackageManifest:
    root: Path
    raw: JsonObject

    @property
    def name(self) -> str:
        return str(self.raw.get("name") or "")

    @property
    def version(self) -> str:
        return str(self.raw.get("version") or "")

    @property
    def description(self) -> str | None:
        value = self.raw.get("description")
        return str(value) if value is not None else None

    @property
    def coding_agents_specifier(self) -> str | None:
        compatibility = self.raw.get("compatibility")
        if not is_json_object(compatibility):
            return None
        value = compatibility.get("coding_agents")
        return str(value) if value is not None else None

    @property
    def team_exports(self) -> list[JsonObject]:
        exports = self.raw.get("exports")
        if not is_json_object(exports):
            return []
        teams = exports.get("teams")
        if not isinstance(teams, list):
            return []
        return [team for team in teams if is_json_object(team)]

    @property
    def skill_dependencies(self) -> list[JsonObject]:
        skills = self.raw.get("skills")
        if not is_json_object(skills):
            return []
        dependencies = skills.get("dependencies")
        if not isinstance(dependencies, list):
            return []
        return [dependency for dependency in dependencies if is_json_object(dependency)]

    @property
    def external_skills(self) -> list[JsonObject]:
        skills = self.raw.get("skills")
        if not is_json_object(skills):
            return []
        external = skills.get("external")
        if not isinstance(external, list):
            return []
        return [skill for skill in external if is_json_object(skill)]

    @property
    def required_env(self) -> tuple[str, ...]:
        requires = self.raw.get("requires")
        if not is_json_object(requires):
            return ()
        env = requires.get("env")
        if not isinstance(env, list):
            return ()
        return tuple(str(name) for name in env if isinstance(name, str) and name)
