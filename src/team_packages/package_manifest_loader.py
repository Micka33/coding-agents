from __future__ import annotations

from pathlib import Path

from src.team_loader.errors.team_loader_error import TeamLoaderError
from src.team_loader.parsing.yaml_parser import YamlParser
from src.type_defs import is_json_object

from src.team_packages.package_error import TeamPackageError
from src.team_packages.package_manifest import PackageManifest


class PackageManifestLoader:
    MANIFEST_NAME = "coding-agents-package.yaml"

    def __init__(self, yaml_parser: YamlParser | None = None) -> None:
        self._yaml_parser = yaml_parser or YamlParser()

    def load(self, package_root: str | Path) -> PackageManifest:
        root = Path(package_root).expanduser().resolve()
        manifest_path = root / self.MANIFEST_NAME
        if not manifest_path.is_file():
            raise TeamPackageError(f"Package manifest does not exist: {manifest_path}")
        try:
            parsed = self._yaml_parser.parse(manifest_path.read_text(encoding="utf-8"))
        except TeamLoaderError as error:
            raise TeamPackageError(f"{manifest_path}: {error}") from error
        if not is_json_object(parsed):
            raise TeamPackageError(f"{manifest_path} must contain a YAML mapping.")
        return PackageManifest(root=root, raw=parsed)
