from __future__ import annotations

import os
import re
from pathlib import Path

from packaging.specifiers import InvalidSpecifier, SpecifierSet
from packaging.version import InvalidVersion, Version

from src.team_instanciator.configuration.runtime_configuration import RuntimeConfiguration
from src.team_instanciator.resolvers.skill_source_resolver import SkillSourceResolver
from src.team_loader.loading.team_loader import TeamLoader
from src.team_loader.models.team_definition import TeamDefinition
from src.team_loader.errors.team_loader_error import TeamLoaderError

from src.team_packages.package_error import TeamPackageError
from src.team_packages.package_manifest import PackageManifest
from src.team_packages.package_manifest_loader import PackageManifestLoader
from src.team_packages.version import current_coding_agents_version


class TeamPackageValidator:
    NAME_RE = re.compile(r"^[a-z0-9-]+(/[a-z0-9-]+)?$")
    VERSION_RE = re.compile(r"^\d+\.\d+\.\d+(?:[-+][0-9A-Za-z.-]+)?$")
    ENV_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
    SKILL_ID_RE = re.compile(r"^[a-z0-9][a-z0-9._-]*$")

    def __init__(
        self,
        manifest_loader: PackageManifestLoader | None = None,
        team_loader: TeamLoader | None = None,
    ) -> None:
        self._manifest_loader = manifest_loader or PackageManifestLoader()
        self._team_loader = team_loader or TeamLoader()

    def validate(self, package_root: str | Path) -> tuple[PackageManifest, list[str], list[TeamDefinition]]:
        manifest = self._manifest_loader.load(package_root)
        errors: list[str] = []
        warnings: list[str] = []
        self._validate_manifest(manifest, errors)
        teams = self._load_exported_teams(manifest, errors)
        self._validate_skill_references(manifest, teams, errors, warnings)
        self._validate_required_env(manifest, errors, warnings)
        if errors:
            raise TeamPackageError("\n".join(errors))
        return manifest, warnings, teams

    def _validate_manifest(self, manifest: PackageManifest, errors: list[str]) -> None:
        if manifest.raw.get("schema_version") != 1:
            errors.append("coding-agents-package.yaml requires schema_version: 1.")
        if not self.NAME_RE.fullmatch(manifest.name):
            errors.append("Package name must use lowercase letters, digits, hyphens, and one optional owner/ prefix.")
        if not self.VERSION_RE.fullmatch(manifest.version):
            errors.append("Package version must be a semantic version like 1.2.3.")
        try:
            Version(manifest.version)
        except InvalidVersion:
            errors.append(f"Package version is not a valid PEP 440 version: {manifest.version!r}.")
        specifier = manifest.coding_agents_specifier
        if specifier:
            try:
                specifier_set = SpecifierSet(specifier)
                current = Version(current_coding_agents_version())
            except (InvalidSpecifier, InvalidVersion) as error:
                errors.append(f"compatibility.coding_agents is invalid: {error}.")
            else:
                if current not in specifier_set:
                    errors.append(
                        f"Package requires coding-agents {specifier}, but current version is {current}."
                    )
        if not manifest.team_exports:
            errors.append("exports.teams must list at least one exported team.")
        self._validate_skill_declarations(manifest, errors)

    def _load_exported_teams(self, manifest: PackageManifest, errors: list[str]) -> list[TeamDefinition]:
        teams: list[TeamDefinition] = []
        for index, export in enumerate(manifest.team_exports, start=1):
            export_id = export.get("id")
            export_path = export.get("path")
            if not isinstance(export_id, str) or not export_id:
                errors.append(f"exports.teams[{index}].id must be a non-empty string.")
                continue
            if not isinstance(export_path, str) or not export_path:
                errors.append(f"exports.teams[{index}].path must be a non-empty string.")
                continue
            try:
                team_path = self._package_relative_path(manifest.root, export_path)
            except TeamPackageError as error:
                errors.append(str(error))
                continue
            try:
                team = self._team_loader.load(team_path)
            except TeamLoaderError as error:
                errors.append(f"{team_path}: {error}")
                continue
            if team.id != export_id:
                errors.append(f"exports.teams[{index}].id '{export_id}' does not match team.yaml id '{team.id}'.")
            teams.append(team)
        return teams

    def _validate_skill_declarations(self, manifest: PackageManifest, errors: list[str]) -> None:
        for index, dependency in enumerate(manifest.skill_dependencies, start=1):
            if not self._valid_skill_id(dependency.get("id")):
                errors.append(f"skills.dependencies[{index}].id must use lowercase letters, digits, dots, underscores, and hyphens.")
            source = dependency.get("source")
            if not isinstance(source, str) or not source.startswith("git:"):
                errors.append(f"skills.dependencies[{index}].source must be a git: source.")
            ref = dependency.get("ref")
            if ref is not None and not isinstance(ref, str):
                errors.append(f"skills.dependencies[{index}].ref must be a string when set.")
        for index, external in enumerate(manifest.external_skills, start=1):
            if not self._valid_skill_id(external.get("id")):
                errors.append(f"skills.external[{index}].id must use lowercase letters, digits, dots, underscores, and hyphens.")
            hint = external.get("install_hint")
            if hint is not None and not isinstance(hint, str):
                errors.append(f"skills.external[{index}].install_hint must be a string when set.")

    def _valid_skill_id(self, skill_id: object) -> bool:
        return isinstance(skill_id, str) and self.SKILL_ID_RE.fullmatch(skill_id) is not None

    def _validate_skill_references(
        self,
        manifest: PackageManifest,
        teams: list[TeamDefinition],
        errors: list[str],
        warnings: list[str],
    ) -> None:
        dependencies = {str(item.get("id")) for item in manifest.skill_dependencies if item.get("id")}
        external = {str(item.get("id")): item for item in manifest.external_skills if item.get("id")}
        visible_external = self._visible_external_skill_ids()
        resolver = SkillSourceResolver(RuntimeConfiguration({"CODEX_HOME": os.environ.get("CODEX_HOME", "")}))
        for team in teams:
            bundled = self._bundled_skill_ids(Path(team.path).parent)
            for agent in team.agents.values():
                selected = resolver.selected_skill_ids(agent)
                if selected is None:
                    continue
                for skill_id in selected:
                    if skill_id in bundled or skill_id in dependencies or skill_id in external:
                        continue
                    errors.append(
                        f"Agent '{agent.id}' references skill '{skill_id}', but it is not bundled, a dependency, or external."
                    )
        for skill_id, external_skill in external.items():
            if skill_id in visible_external:
                continue
            hint = external_skill.get("install_hint")
            suffix = f" Install with: {hint}" if hint else ""
            warnings.append(f"External skill '{skill_id}' is not installed in project or user skill layers.{suffix}")

    def _validate_required_env(self, manifest: PackageManifest, errors: list[str], warnings: list[str]) -> None:
        for name in manifest.required_env:
            if not self.ENV_RE.fullmatch(name):
                errors.append(f"requires.env contains invalid environment variable name: {name!r}.")
            elif not os.environ.get(name):
                warnings.append(f"Required environment variable '{name}' is not set.")

    def _package_relative_path(self, root: Path, raw_path: str) -> Path:
        path = Path(raw_path)
        if path.is_absolute():
            raise TeamPackageError(f"Package paths must be relative: {raw_path}")
        resolved = (root / path).resolve()
        try:
            resolved.relative_to(root)
        except ValueError as error:
            raise TeamPackageError(f"Package path must stay within the package: {raw_path}") from error
        return resolved

    def _bundled_skill_ids(self, team_dir: Path) -> set[str]:
        skills_dir = team_dir / "skills"
        if not skills_dir.is_dir():
            return set()
        return {child.name for child in skills_dir.iterdir() if (child / "SKILL.md").is_file()}

    def _visible_external_skill_ids(self) -> set[str]:
        roots = [Path.cwd() / ".agents" / "skills"]
        codex_home = os.environ.get("CODEX_HOME")
        if codex_home:
            roots.append(Path(codex_home).expanduser() / "skills")
        skill_ids: set[str] = set()
        for root in roots:
            if not root.is_dir():
                continue
            skill_ids.update(child.name for child in root.iterdir() if (child / "SKILL.md").is_file())
        return skill_ids
