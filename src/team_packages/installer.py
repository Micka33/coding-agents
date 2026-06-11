from __future__ import annotations

from pathlib import Path
import re
import shutil
import subprocess
import tempfile

from src.team_loader.models.team_definition import TeamDefinition
from src.type_defs import JsonObject

from src.team_packages.content_hasher import ContentHasher
from src.team_packages.locked_package import LockedPackage
from src.team_packages.lockfile_store import TeamLockfileStore
from src.team_packages.package_error import TeamPackageError
from src.team_packages.package_manifest import PackageManifest
from src.team_packages.package_validator import TeamPackageValidator
from src.team_packages.risk_scanner import PackageRiskScanner
from src.team_packages.staged_skill_dependency import StagedSkillDependency


class TeamPackageInstaller:
    _ALLOWED_URL_PREFIXES = ("https://", "ssh://", "git://", "file://", "/")
    _SCP_SOURCE_RE = re.compile(r"^[A-Za-z0-9._-]+@[A-Za-z0-9._-]+:[^:]+$")

    def __init__(
        self,
        workspace_dir: Path | None = None,
        validator: TeamPackageValidator | None = None,
        lockfile_store: TeamLockfileStore | None = None,
    ) -> None:
        self._workspace_dir = (workspace_dir or Path.cwd()).resolve()
        self._validator = validator or TeamPackageValidator()
        self._lockfile_store = lockfile_store or TeamLockfileStore(self._workspace_dir)
        self._hasher = ContentHasher()
        self._risk_scanner = PackageRiskScanner()

    def install(self, source: str) -> tuple[LockedPackage, list[str]]:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_dir = Path(tmp)
            source_root, source_label, requested, resolved = self._resolve_package_source(source, tmp_dir)
            manifest, warnings, teams = self._validator.validate(source_root)
            self._warn_on_git_version_mismatch(manifest, requested, warnings)
            staged_skills = [
                self._stage_skill_dependency(dependency, tmp_dir / f"skill-{index}")
                for index, dependency in enumerate(manifest.skill_dependencies)
            ]
            self._ensure_no_skill_conflicts(manifest.name, staged_skills)
            risk_flags = self._risk_flags(teams)
            installed_path = self._installed_package_path(manifest.name)
            self._replace_tree(source_root, installed_path)
            integrity = self._hasher.hash_directory(installed_path)
            skill_entries = [self._commit_skill_dependency(staged) for staged in staged_skills]
            entry: JsonObject = {
                "name": manifest.name,
                "version": manifest.version,
                "source": source_label,
                "requested": requested,
                "resolved": resolved or integrity,
                "integrity": integrity,
                "installed_path": self._lockfile_store.relative_path(installed_path),
                "teams": self._team_entries(manifest),
                "risk_flags": risk_flags,
                "requires": {"env": list(manifest.required_env)},
                "compatibility": {
                    "coding_agents": manifest.coding_agents_specifier,
                },
                "dependencies": {
                    "skills": skill_entries,
                },
            }
            self._lockfile_store.upsert_package(entry)
            return LockedPackage(raw=entry), warnings

    def update(self, package_name: str | None = None) -> list[LockedPackage]:
        packages = self._lockfile_store.packages()
        if package_name:
            packages = [package for package in packages if package.name == package_name]
            if not packages:
                raise TeamPackageError(f"Package is not installed: {package_name}")
        updated: list[LockedPackage] = []
        for package in packages:
            source = package.source
            requested = package.requested
            install_source = f"{source}@{requested}" if source.startswith("git:") and requested else source
            updated.append(self.install(install_source)[0])
        return updated

    def uninstall(self, package_name: str) -> LockedPackage:
        package = next(
            (item for item in self._lockfile_store.packages() if item.name == package_name),
            None,
        )
        if package is None:
            raise TeamPackageError(f"Package is not installed: {package_name}")
        installed_path = self._locked_package_path(package)
        self._lockfile_store.remove_package(package_name)
        if installed_path.exists():
            shutil.rmtree(installed_path)
        self._remove_unused_skill_dependencies(package)
        return package

    def _resolve_package_source(self, source: str, tmp_dir: Path) -> tuple[Path, str, str | None, str | None]:
        if source.startswith("git:"):
            repo_url, requested = self._split_git_source(source)
            checkout_dir = tmp_dir / "package"
            self._clone_and_checkout(repo_url, requested, checkout_dir)
            resolved = self._git(["-C", str(checkout_dir), "rev-parse", "HEAD"]).strip()
            return checkout_dir, f"git:{repo_url}", requested, resolved
        source_path = Path(source).expanduser().resolve()
        if not source_path.is_dir():
            raise TeamPackageError(f"Package source does not exist: {source}")
        return source_path, self._local_source_label(source, source_path), None, None

    def _split_git_source(self, source: str) -> tuple[str, str | None]:
        body = source.removeprefix("git:")
        ref_marker = body.rfind("@")
        if ref_marker > self._repo_path_start(body):
            return body[:ref_marker], body[ref_marker + 1 :]
        return body, None

    def _repo_path_start(self, body: str) -> int:
        scheme_marker = body.find("://")
        if scheme_marker != -1:
            path_marker = body.find("/", scheme_marker + 3)
            return path_marker if path_marker != -1 else len(body)
        scp_marker = body.find(":")
        if scp_marker != -1:
            return scp_marker
        return 0

    def _clone_and_checkout(self, repo_url: str, requested: str | None, checkout_dir: Path) -> None:
        self._git(
            [
                "-c",
                "protocol.ext.allow=never",
                "clone",
                "--quiet",
                "--",
                self._validated_repo_url(repo_url),
                str(checkout_dir),
            ]
        )
        if requested:
            self._git(["-C", str(checkout_dir), "checkout", "--quiet", self._validated_git_ref(requested), "--"])

    def _validated_repo_url(self, repo_url: str) -> str:
        allowed = repo_url.startswith(self._ALLOWED_URL_PREFIXES) or self._SCP_SOURCE_RE.fullmatch(repo_url)
        if not repo_url or repo_url.startswith("-") or "::" in repo_url or not allowed:
            raise TeamPackageError(f"Unsupported git source: {repo_url!r}")
        return repo_url

    def _validated_git_ref(self, ref: str) -> str:
        if ref.startswith("-") or any(character.isspace() for character in ref):
            raise TeamPackageError(f"Unsupported git ref: {ref!r}")
        return ref

    def _installed_package_path(self, package_name: str) -> Path:
        root = self._lockfile_store.packages_root
        path = self._lockfile_store.contained_path(root.joinpath(*package_name.split("/")), root)
        if path is None:
            raise TeamPackageError(f"Package name escapes the packages directory: {package_name!r}")
        return path

    def _locked_package_path(self, package: LockedPackage) -> Path:
        path = self._lockfile_store.contained_path(
            package.installed_path_value,
            self._lockfile_store.packages_root,
        )
        if path is None:
            raise TeamPackageError(
                f"Locked installed_path escapes the packages directory: {package.installed_path_value!r}"
            )
        return path

    def _replace_tree(self, source: Path, destination: Path) -> None:
        if destination.exists():
            shutil.rmtree(destination)
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copytree(
            source,
            destination,
            ignore=shutil.ignore_patterns(".git", "__pycache__", ".DS_Store"),
        )

    def _stage_skill_dependency(self, dependency: JsonObject, stage_dir: Path) -> StagedSkillDependency:
        skill_id = str(dependency.get("id") or "")
        source = str(dependency.get("source") or "")
        requested = str(dependency.get("ref") or "") or None
        if not source.startswith("git:"):
            raise TeamPackageError(f"Skill dependency '{skill_id}' must use a git: source.")
        repo_url, source_ref = self._split_git_source(source)
        requested = requested or source_ref
        checkout_dir = stage_dir / "skill"
        self._clone_and_checkout(repo_url, requested, checkout_dir)
        resolved = self._git(["-C", str(checkout_dir), "rev-parse", "HEAD"]).strip()
        return StagedSkillDependency(
            skill_id=skill_id,
            repo_url=repo_url,
            requested=requested,
            resolved=resolved,
            source_dir=self._skill_source_dir(checkout_dir, skill_id),
        )

    def _commit_skill_dependency(self, staged: StagedSkillDependency) -> JsonObject:
        installed_path = self._installed_skill_path(staged.skill_id)
        self._replace_tree(staged.source_dir, installed_path)
        return {
            "id": staged.skill_id,
            "source": f"git:{staged.repo_url}",
            "requested": staged.requested,
            "resolved": staged.resolved,
            "integrity": self._hasher.hash_directory(installed_path),
            "installed_path": self._lockfile_store.relative_path(installed_path),
        }

    def _installed_skill_path(self, skill_id: str) -> Path:
        root = self._lockfile_store.skills_root
        path = self._lockfile_store.contained_path(root / skill_id, root)
        if path is None:
            raise TeamPackageError(f"Skill dependency id escapes the skills directory: {skill_id!r}")
        return path

    def _skill_source_dir(self, checkout_dir: Path, skill_id: str) -> Path:
        candidates = [
            checkout_dir,
            checkout_dir / skill_id,
            checkout_dir / ".agents" / "skills" / skill_id,
            checkout_dir / "skills" / skill_id,
        ]
        for candidate in candidates:
            if (candidate / "SKILL.md").is_file():
                return candidate
        raise TeamPackageError(f"Skill dependency '{skill_id}' does not contain SKILL.md.")

    def _team_entries(self, manifest: PackageManifest) -> list[JsonObject]:
        entries: list[JsonObject] = []
        for export in manifest.team_exports:
            entries.append({"id": str(export.get("id")), "path": str(export.get("path"))})
        return entries

    def _risk_flags(self, teams: list[TeamDefinition]) -> list[str]:
        flags: set[str] = set()
        for team in teams:
            flags.update(self._risk_scanner.risk_flags(team))
        order = ["custom_tools", "stdio_mcp", "remote_mcp", "shell"]
        return [flag for flag in order if flag in flags]

    def _ensure_no_skill_conflicts(self, package_name: str, staged_skills: list[StagedSkillDependency]) -> None:
        staged_by_id = {staged.skill_id: staged for staged in staged_skills}
        for package in self._lockfile_store.packages():
            if package.name == package_name:
                continue
            for skill in package.skill_dependencies:
                staged = staged_by_id.get(skill.id)
                if staged is not None and skill.resolved != staged.resolved:
                    raise TeamPackageError(
                        f"Skill dependency '{skill.id}' is already locked by package "
                        f"'{package.name}' at {skill.resolved}, but '{package_name}' requires "
                        f"{staged.resolved}. Align the skill refs or uninstall the conflicting package."
                    )

    def _remove_unused_skill_dependencies(self, removed: LockedPackage) -> None:
        if not removed.skill_dependencies:
            return
        remaining_paths = self._remaining_skill_dependency_paths()
        for skill in removed.skill_dependencies:
            installed_path = self._lockfile_store.contained_path(
                skill.installed_path_value,
                self._lockfile_store.skills_root,
            )
            if installed_path is None or installed_path in remaining_paths:
                continue
            if installed_path.exists():
                shutil.rmtree(installed_path)

    def _remaining_skill_dependency_paths(self) -> set[Path]:
        return {
            self._lockfile_store.absolute_path(skill.installed_path_value).resolve()
            for package in self._lockfile_store.packages()
            for skill in package.skill_dependencies
        }

    def _local_source_label(self, raw_source: str, source_path: Path) -> str:
        if not Path(raw_source).is_absolute():
            return raw_source
        home = Path.home().resolve()
        try:
            return f"~/{source_path.relative_to(home).as_posix()}"
        except ValueError:
            return self._lockfile_store.relative_path(source_path)

    def _warn_on_git_version_mismatch(
        self,
        manifest: PackageManifest,
        requested: str | None,
        warnings: list[str],
    ) -> None:
        if requested is None:
            return
        normalized = requested.removeprefix("v")
        if normalized and normalized[0].isdigit() and normalized != manifest.version:
            warnings.append(
                f"Git ref '{requested}' does not match package manifest version '{manifest.version}'."
            )

    def _git(self, args: list[str]) -> str:
        result = subprocess.run(
            ["git", *args],
            check=False,
            capture_output=True,
            text=True,
            cwd=self._workspace_dir,
        )
        if result.returncode != 0:
            message = result.stderr.strip() or result.stdout.strip() or "git command failed"
            raise TeamPackageError(message)
        return result.stdout
