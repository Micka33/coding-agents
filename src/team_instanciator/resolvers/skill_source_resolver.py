from __future__ import annotations

import logging
import os
import re
from pathlib import Path

from src.type_defs import is_json_object
from src.team_loader.models.agent_definition import AgentDefinition
from src.team_loader.models.team_definition import TeamDefinition

from src.team_instanciator.configuration.runtime_configuration import RuntimeConfiguration
from src.team_instanciator.errors.team_instanciator_error import TeamInstanciatorError
from src.team_instanciator.resolvers.resolved_skill_source import ResolvedSkillSource
from src.team_packages.package_locator import InstalledPackageLocator

logger = logging.getLogger(__name__)


class SkillSourceResolver:
    def __init__(self, configuration: RuntimeConfiguration | None = None) -> None:
        self._configuration = configuration or RuntimeConfiguration()

    def resolve_team_sources(self, team: TeamDefinition) -> tuple[ResolvedSkillSource, ...]:
        candidates: list[tuple[Path, str, str, tuple[str, ...] | None]] = []
        home = self._configuration.get("CODEX_HOME")
        if home is None:
            home = os.environ.get("CODEX_HOME")
        if home:
            candidates.append((Path(home) / "skills", "User", "user", None))
        candidates.append((self._launch_cwd(team) / ".agents" / "skills", "Project", "project", None))
        package_source = self._package_skill_source(team)
        if package_source is not None:
            candidates.append(package_source)

        team_skills = self._team_dir(team) / "skills"
        if team_skills.is_dir():
            candidates.append((team_skills, "Team", "team", None))

        for index, configured in enumerate(getattr(team, "skill_sources", ()), start=1):
            candidates.append(
                (
                    self._resolve_team_source(team, configured),
                    f"Team Source {index}",
                    f"team-source-{index}",
                    None,
                )
            )

        existing = [
            (path.resolve(), label, slug, allowed_skill_ids)
            for path, label, slug, allowed_skill_ids in candidates
            if self._source_exists(path, label)
        ]
        return self._dedupe_and_virtualize(existing)

    def resolve_agent_sources(self, team: TeamDefinition, agent: AgentDefinition) -> tuple[ResolvedSkillSource, ...]:
        if self._skills_disabled(agent):
            return ()
        selected = self.selected_skill_ids(agent)
        sources = self.resolve_team_sources(team)
        if selected is None:
            return sources
        missing = sorted(set(selected) - self._available_skill_ids(sources))
        if missing:
            raise TeamInstanciatorError(f"Agent '{agent.id}' references unknown skill id '{missing[0]}'.")
        agent_prefix = f"/skills/{self._slug(agent.id)}"
        return tuple(
            ResolvedSkillSource(
                host_path=source.host_path,
                virtual_path=f"{agent_prefix}/{self._source_slug(source.virtual_path)}",
                label=source.label,
                allowed_skill_ids=self._intersected_skill_ids(source, selected),
            )
            for source in sources
            if self._source_contains_any(source, selected)
        )

    def selected_skill_ids(self, agent: AgentDefinition) -> tuple[str, ...] | None:
        skills = getattr(agent, "skills", "inherit")
        if isinstance(skills, list):
            return tuple(str(skill_id) for skill_id in skills if isinstance(skill_id, str) and skill_id)
        if is_json_object(skills):
            raw_only = skills.get("only")
            if isinstance(raw_only, list):
                return tuple(str(skill_id) for skill_id in raw_only if isinstance(skill_id, str) and skill_id)
        return None

    def read_permission_paths(self, team: TeamDefinition, agent: AgentDefinition) -> list[str]:
        paths: list[str] = []
        for source in self.resolve_agent_sources(team, agent):
            if source.allowed_skill_ids is None:
                paths.extend([source.virtual_path, f"{source.virtual_path}/**"])
                continue
            for skill_id in source.allowed_skill_ids:
                if self._skill_exists(source.host_path, skill_id):
                    base = f"{source.virtual_path}/{skill_id}"
                    paths.extend([base, f"{base}/**"])
        return paths

    def _intersected_skill_ids(self, source: ResolvedSkillSource, selected: tuple[str, ...]) -> tuple[str, ...]:
        if source.allowed_skill_ids is None:
            return selected
        return tuple(skill_id for skill_id in selected if skill_id in source.allowed_skill_ids)

    def _dedupe_and_virtualize(
        self,
        sources: list[tuple[Path, str, str, tuple[str, ...] | None]],
    ) -> tuple[ResolvedSkillSource, ...]:
        by_path: dict[Path, tuple[Path, str, str, tuple[str, ...] | None]] = {}
        order: list[Path] = []
        for source in sources:
            path = source[0]
            if path in by_path:
                order.remove(path)
            by_path[path] = source
            order.append(path)

        used_virtual_paths: set[str] = set()
        resolved: list[ResolvedSkillSource] = []
        for path in order:
            host_path, label, slug, allowed_skill_ids = by_path[path]
            virtual_path = self._unique_virtual_path(f"/skills/{slug}", used_virtual_paths)
            resolved.append(
                ResolvedSkillSource(
                    host_path=host_path,
                    virtual_path=virtual_path,
                    label=label,
                    allowed_skill_ids=allowed_skill_ids,
                )
            )
        return tuple(resolved)

    def _unique_virtual_path(self, base_path: str, used_paths: set[str]) -> str:
        path = base_path
        index = 2
        while path in used_paths:
            path = f"{base_path}-{index}"
            index += 1
        used_paths.add(path)
        return path

    def _source_exists(self, path: Path, label: str) -> bool:
        if path.is_dir():
            return True
        if label.startswith("Team Source"):
            logger.warning("Configured skill source does not exist: %s", path)
        return False

    def _source_contains_any(self, source: ResolvedSkillSource, skill_ids: tuple[str, ...]) -> bool:
        if source.allowed_skill_ids is not None:
            skill_ids = tuple(skill_id for skill_id in skill_ids if skill_id in source.allowed_skill_ids)
        return any(self._skill_exists(source.host_path, skill_id) for skill_id in skill_ids)

    def _available_skill_ids(self, sources: tuple[ResolvedSkillSource, ...]) -> set[str]:
        available: set[str] = set()
        for source in sources:
            if source.allowed_skill_ids is not None:
                available.update(
                    skill_id
                    for skill_id in source.allowed_skill_ids
                    if self._skill_exists(source.host_path, skill_id)
                )
                continue
            available.update(
                child.name
                for child in source.host_path.iterdir()
                if self._skill_exists(source.host_path, child.name)
            )
        return available

    def _skill_exists(self, source_path: Path, skill_id: str) -> bool:
        return (source_path / skill_id / "SKILL.md").is_file()

    def _skills_disabled(self, agent: AgentDefinition) -> bool:
        return getattr(agent, "skills", "inherit") == "none"

    def _resolve_team_source(self, team: TeamDefinition, configured: str) -> Path:
        path = Path(configured).expanduser()
        if path.is_absolute():
            return path
        return (self._team_dir(team) / path).resolve()

    def _team_dir(self, team: TeamDefinition) -> Path:
        return Path(getattr(team, "path", "team.yaml")).expanduser().resolve().parent

    def _launch_cwd(self, team: TeamDefinition) -> Path:
        return Path(getattr(team, "load_cwd", Path.cwd())).expanduser().resolve()

    def _package_skill_source(self, team: TeamDefinition) -> tuple[Path, str, str, tuple[str, ...]] | None:
        locator = InstalledPackageLocator(self._launch_cwd(team))
        locked_skill_ids = locator.locked_skill_ids(getattr(team, "path", self._team_dir(team) / "team.yaml"))
        if not locked_skill_ids:
            return None
        package_skills = self._launch_cwd(team) / ".coding-agents" / "skills"
        if not package_skills.is_dir():
            return None
        return package_skills, "Package", "package", locked_skill_ids

    def _source_slug(self, virtual_path: str) -> str:
        return virtual_path.strip("/").split("/")[-1]

    def _slug(self, value: str) -> str:
        slug = re.sub(r"[^a-z0-9-]+", "-", value.casefold()).strip("-")
        return slug or "agent"
