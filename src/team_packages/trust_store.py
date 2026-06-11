from __future__ import annotations

import json
import os
from pathlib import Path

from src.type_defs import JsonObject, is_json_object

from src.team_packages.locked_package import LockedPackage


class TeamPackageTrustStore:
    """User-local trust decisions, resolved from CODEX_HOME or the home directory.

    The gate, `team trust`, and Studio discovery must all read and write the
    same file, so the path resolution deliberately ignores per-run
    runtime configuration.
    """

    @property
    def path(self) -> Path:
        configured = os.environ.get("CODEX_HOME")
        home = Path(configured).expanduser() if configured else Path.home() / ".codex"
        return home / "coding-agents" / "trust.json"

    def is_trusted(self, package_name: str, integrity: str) -> bool:
        trusted = self._read().get("trusted_packages", [])
        if not isinstance(trusted, list):
            return False
        return any(
            is_json_object(item) and item.get("name") == package_name and item.get("integrity") == integrity
            for item in trusted
        )

    def trust(self, package_name: str, integrity: str) -> None:
        data = self._read()
        trusted = [item for item in data.get("trusted_packages", []) if is_json_object(item)]
        if not any(item.get("name") == package_name and item.get("integrity") == integrity for item in trusted):
            trusted.append({"name": package_name, "integrity": integrity})
        trusted.sort(key=lambda item: (str(item.get("name") or ""), str(item.get("integrity") or "")))
        data["schema_version"] = 1
        data["trusted_packages"] = trusted
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    def status(self, package: LockedPackage) -> str:
        if not package.risk_flags:
            return "not_required"
        return "trusted" if self.is_trusted(package.name, package.integrity) else "untrusted"

    def _read(self) -> JsonObject:
        if not self.path.is_file():
            return {"schema_version": 1, "trusted_packages": []}
        try:
            parsed = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {"schema_version": 1, "trusted_packages": []}
        if not is_json_object(parsed):
            return {"schema_version": 1, "trusted_packages": []}
        parsed.setdefault("schema_version", 1)
        parsed.setdefault("trusted_packages", [])
        return parsed
