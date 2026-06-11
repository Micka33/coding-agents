from __future__ import annotations

from pathlib import Path

from src.team_packages.locked_package import LockedPackage
from src.team_packages.lockfile_store import TeamLockfileStore
from src.team_packages.package_error import TeamPackageError


class InstalledPackageLocator:
    def __init__(self, workspace_dir: Path | None = None) -> None:
        self._lockfile_store = TeamLockfileStore(workspace_dir)

    def package_for_team_file(self, team_file: str | Path) -> LockedPackage | None:
        team_path = Path(team_file).expanduser().resolve()
        for package in self._packages():
            installed_path = self.installed_package_path(package)
            if installed_path is None:
                continue
            try:
                team_path.relative_to(installed_path)
            except ValueError:
                continue
            return package
        return None

    def installed_package_path(self, package: LockedPackage) -> Path | None:
        return self._lockfile_store.contained_path(
            package.installed_path_value,
            self._lockfile_store.packages_root,
        )

    def is_installed_package_path(self, team_file: str | Path) -> bool:
        team_path = Path(team_file).expanduser().resolve()
        packages_dir = self._lockfile_store.packages_root.resolve()
        try:
            team_path.relative_to(packages_dir)
        except ValueError:
            return False
        return True

    def locked_skill_ids(self, team_file: str | Path) -> tuple[str, ...]:
        package = self.package_for_team_file(team_file)
        if package is None:
            return ()
        return tuple(skill.id for skill in package.skill_dependencies if skill.id)

    def _packages(self) -> list[LockedPackage]:
        try:
            return self._lockfile_store.packages()
        except TeamPackageError:
            return []
