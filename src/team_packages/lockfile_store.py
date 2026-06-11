from __future__ import annotations

import json
from pathlib import Path

from src.type_defs import JsonObject, is_json_object

from src.team_packages.locked_package import LockedPackage
from src.team_packages.package_error import TeamPackageError
from src.team_packages.version import current_coding_agents_version


class TeamLockfileStore:
    LOCKFILE = Path(".coding-agents") / "team-lock.json"
    PACKAGES_DIR = Path(".coding-agents") / "packages"
    SKILLS_DIR = Path(".coding-agents") / "skills"

    def __init__(self, workspace_dir: Path | None = None) -> None:
        self._workspace_dir = (workspace_dir or Path.cwd()).resolve()

    @property
    def path(self) -> Path:
        return self._workspace_dir / self.LOCKFILE

    @property
    def packages_root(self) -> Path:
        return self._workspace_dir / self.PACKAGES_DIR

    @property
    def skills_root(self) -> Path:
        return self._workspace_dir / self.SKILLS_DIR

    def read(self) -> JsonObject:
        if not self.path.is_file():
            return self._empty()
        try:
            parsed = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as error:
            raise TeamPackageError(f"Team lockfile is unreadable: {self.path} ({error})") from error
        if not is_json_object(parsed):
            raise TeamPackageError(f"Team lockfile is unreadable: {self.path} (expected a JSON object)")
        parsed.setdefault("schema_version", 1)
        parsed.setdefault("generated_by", self._generated_by())
        parsed.setdefault("packages", [])
        return parsed

    def packages(self) -> list[LockedPackage]:
        packages = self.read().get("packages", [])
        if not isinstance(packages, list):
            return []
        return [LockedPackage(raw=package) for package in packages if is_json_object(package)]

    def write(self, lockfile: JsonObject) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        lockfile["schema_version"] = 1
        lockfile["generated_by"] = self._generated_by()
        self.path.write_text(json.dumps(lockfile, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    def upsert_package(self, entry: JsonObject) -> None:
        lockfile = self.read()
        packages = [package for package in lockfile.get("packages", []) if is_json_object(package)]
        packages = [package for package in packages if package.get("name") != entry.get("name")]
        packages.append(entry)
        packages.sort(key=lambda package: str(package.get("name") or ""))
        lockfile["packages"] = packages
        self.write(lockfile)

    def remove_package(self, package_name: str) -> JsonObject | None:
        lockfile = self.read()
        packages = [package for package in lockfile.get("packages", []) if is_json_object(package)]
        removed = next((package for package in packages if package.get("name") == package_name), None)
        lockfile["packages"] = [package for package in packages if package.get("name") != package_name]
        self.write(lockfile)
        return removed

    def relative_path(self, path: Path) -> str:
        resolved = path.expanduser().resolve()
        try:
            return resolved.relative_to(self._workspace_dir).as_posix()
        except ValueError:
            return resolved.as_posix()

    def absolute_path(self, path_value: object) -> Path:
        path = Path(str(path_value or ""))
        if path.is_absolute():
            return path
        return (self._workspace_dir / path).resolve()

    def contained_path(self, path_value: object, root: Path) -> Path | None:
        resolved = self.absolute_path(path_value).resolve()
        resolved_root = root.resolve()
        if resolved == resolved_root:
            return None
        try:
            resolved.relative_to(resolved_root)
        except ValueError:
            return None
        return resolved

    def _empty(self) -> JsonObject:
        return {"schema_version": 1, "generated_by": self._generated_by(), "packages": []}

    def _generated_by(self) -> str:
        return f"coding-agents {current_coding_agents_version()}"
