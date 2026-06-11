from __future__ import annotations

from dataclasses import dataclass

from src.type_defs import JsonObject, is_json_object

from src.team_packages.locked_package_team import LockedPackageTeam
from src.team_packages.locked_skill_dependency import LockedSkillDependency


@dataclass(frozen=True)
class LockedPackage:
    """Typed view over one raw `team-lock.json` package entry."""

    raw: JsonObject

    @property
    def name(self) -> str:
        return str(self.raw.get("name") or "")

    @property
    def version(self) -> str:
        return str(self.raw.get("version") or "")

    @property
    def source(self) -> str:
        return str(self.raw.get("source") or "")

    @property
    def requested(self) -> str | None:
        requested = self.raw.get("requested")
        return str(requested) if requested else None

    @property
    def integrity(self) -> str:
        return str(self.raw.get("integrity") or "")

    @property
    def installed_path_value(self) -> object:
        return self.raw.get("installed_path")

    @property
    def risk_flags(self) -> tuple[str, ...]:
        flags = self.raw.get("risk_flags")
        if not isinstance(flags, list):
            return ()
        return tuple(str(flag) for flag in flags)

    @property
    def required_env(self) -> tuple[str, ...]:
        requires = self.raw.get("requires")
        if not is_json_object(requires):
            return ()
        env = requires.get("env")
        if not isinstance(env, list):
            return ()
        return tuple(name for name in env if isinstance(name, str) and name)

    @property
    def teams(self) -> tuple[LockedPackageTeam, ...]:
        teams = self.raw.get("teams")
        if not isinstance(teams, list):
            return ()
        return tuple(LockedPackageTeam(raw=team) for team in teams if is_json_object(team))

    @property
    def skill_dependencies(self) -> tuple[LockedSkillDependency, ...]:
        dependencies = self.raw.get("dependencies")
        if not is_json_object(dependencies):
            return ()
        skills = dependencies.get("skills")
        if not isinstance(skills, list):
            return ()
        return tuple(LockedSkillDependency(raw=skill) for skill in skills if is_json_object(skill))
