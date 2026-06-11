from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from src.team_loader.parsing.yaml_parser import YamlParser
from src.type_defs import is_json_object
from src.team_packages.locked_package import LockedPackage
from src.team_packages.locked_package_team import LockedPackageTeam
from src.team_packages.lockfile_store import TeamLockfileStore
from src.team_packages.package_error import TeamPackageError
from src.team_packages.trust_store import TeamPackageTrustStore


class TeamDiscoveryService:
    def __init__(
        self,
        *,
        repository_root: Path,
        workspace_dir: Path,
        yaml_parser: YamlParser | None = None,
    ) -> None:
        self._repository_root = repository_root.resolve()
        self._workspace_dir = workspace_dir.resolve()
        self._yaml_parser = yaml_parser or YamlParser()

    def discover(self, *, explicit_team_file: str | Path | None = None) -> dict[str, Any]:
        teams = []
        seen_paths: set[Path] = set()
        for team_file, source, package in self._candidate_files(explicit_team_file):
            resolved = team_file.expanduser().resolve()
            if resolved in seen_paths:
                continue
            seen_paths.add(resolved)
            descriptor = self._descriptor(resolved, source, package=package)
            if descriptor is not None and (descriptor["conversation_available"] or descriptor.get("lock_status") == "missing"):
                teams.append(descriptor)

        duplicate_ids = self._duplicate_ids(teams)
        colliding_files = {
            team_file
            for duplicate in duplicate_ids
            for team_file in duplicate.get("team_files", [])
        }
        available_teams = [team for team in teams if str(team["team_file"]) not in colliding_files]
        return {
            "status": "blocked" if duplicate_ids and not available_teams else "ready",
            "teams": available_teams,
            "duplicate_ids": duplicate_ids,
        }

    def _candidate_files(self, explicit_team_file: str | Path | None) -> list[tuple[Path, str, dict[str, Any] | None]]:
        candidates: list[tuple[Path, str, dict[str, Any] | None]] = []
        if explicit_team_file is not None:
            candidates.append((Path(explicit_team_file), "explicit", None))
        candidates.extend(
            (path, "project", None)
            for path in sorted((self._workspace_dir / ".coding-agents" / "teams").glob("*/team.yaml"))
        )
        candidates.extend(self._package_candidate_files())
        candidates.extend(
            (path, "builtin", None)
            for path in sorted((self._repository_root / "teams").glob("*/team.yaml"))
        )
        return candidates

    def _package_candidate_files(self) -> list[tuple[Path, str, dict[str, Any]]]:
        candidates: list[tuple[Path, str, dict[str, Any]]] = []
        trust_store = TeamPackageTrustStore()
        lockfile_store = TeamLockfileStore(self._workspace_dir)
        for package in self._locked_packages(lockfile_store):
            installed_path = lockfile_store.contained_path(package.installed_path_value, lockfile_store.packages_root)
            if installed_path is None:
                continue
            for team in package.teams:
                team_path = lockfile_store.contained_path(installed_path / team.path, installed_path)
                if team_path is None:
                    continue
                metadata = self._package_metadata(package, team, installed_path, team_path, trust_store)
                candidates.append((team_path, "package", metadata))
        return candidates

    def _locked_packages(self, lockfile_store: TeamLockfileStore) -> list[LockedPackage]:
        try:
            return lockfile_store.packages()
        except TeamPackageError:
            return []

    def _descriptor(self, team_file: Path, source: str, package: dict[str, Any] | None = None) -> dict[str, Any] | None:
        if not team_file.is_file():
            if package is not None:
                return self._missing_package_descriptor(team_file, package)
            return None
        try:
            parsed = self._yaml_parser.parse(team_file.read_text(encoding="utf-8"))
        except OSError:
            return None
        if not is_json_object(parsed):
            return None
        team_id = parsed.get("id")
        if not team_id:
            return None
        description = parsed.get("description")
        participants = self._participants(parsed)
        return {
            **(package or {}),
            "team_id": str(team_id),
            "description": str(description) if description is not None else None,
            "team_file": str(team_file),
            "source": source,
            "conversation_available": "conversation" in parsed,
            "participants": participants,
            "participant_aliases": self._participant_aliases(parsed, participants),
        }

    def _missing_package_descriptor(self, team_file: Path, package: dict[str, Any]) -> dict[str, Any] | None:
        team_id = package.get("team_id")
        if not team_id:
            return None
        return {
            **package,
            "team_id": str(team_id),
            "description": None,
            "team_file": str(team_file),
            "source": "package",
            "conversation_available": False,
            "participants": [],
            "participant_aliases": {},
        }

    def _participants(self, parsed: dict[str, Any]) -> list[str]:
        agents = parsed.get("agents")
        if not is_json_object(agents):
            return []
        participants = []
        for agent_id, raw_agent in agents.items():
            if not is_json_object(raw_agent) or "conversation" not in raw_agent:
                continue
            if raw_agent.get("kind") != "deepagent":
                continue
            participants.append(str(agent_id))
        return participants

    def _participant_aliases(self, parsed: dict[str, Any], participants: list[str]) -> dict[str, list[str]]:
        agents = parsed.get("agents")
        if not is_json_object(agents):
            return {}
        aliases_by_participant = {}
        for participant in participants:
            raw_agent = agents.get(participant)
            if not is_json_object(raw_agent):
                continue
            conversation = raw_agent.get("conversation")
            if not is_json_object(conversation):
                aliases_by_participant[participant] = []
                continue
            aliases = conversation.get("aliases")
            aliases_by_participant[participant] = [str(alias) for alias in aliases] if isinstance(aliases, list) else []
        return aliases_by_participant

    def _duplicate_ids(self, teams: list[dict[str, Any]]) -> list[dict[str, Any]]:
        grouped: dict[str, list[dict[str, Any]]] = {}
        for team in teams:
            grouped.setdefault(str(team["team_id"]).casefold(), []).append(team)
        duplicate_ids = []
        for normalized_id, group in sorted(grouped.items()):
            if len(group) < 2:
                continue
            duplicate_ids.append(
                {
                    "team_id": str(group[0]["team_id"]),
                    "normalized_id": normalized_id,
                    "team_files": [str(team["team_file"]) for team in group],
                }
            )
        return duplicate_ids

    def _package_metadata(
        self,
        package: LockedPackage,
        team: LockedPackageTeam,
        installed_path: Path,
        team_path: Path,
        trust_store: TeamPackageTrustStore,
    ) -> dict[str, Any]:
        missing_env = self._missing_required_env(package)
        return {
            "team_id": team.id,
            "package_name": package.name,
            "package_version": package.version,
            "package_source": package.source,
            "lock_status": "locked" if installed_path.exists() and team_path.is_file() else "missing",
            "trust_status": trust_store.status(package),
            "risk_flags": list(package.risk_flags),
            "missing_required_env": missing_env,
            "warnings": [f"Required environment variable '{name}' is not set." for name in missing_env],
        }

    def _missing_required_env(self, package: LockedPackage) -> list[str]:
        return [name for name in package.required_env if not os.environ.get(name)]


def duplicate_team_id_message(discovery: dict[str, Any]) -> str | None:
    duplicates = discovery.get("duplicate_ids")
    if not isinstance(duplicates, list) or not duplicates:
        return None
    blocked = discovery.get("status") == "blocked"
    lines = [
        "Studio team discovery failed: duplicate team ids."
        if blocked
        else "Studio team discovery hid colliding team ids.",
        "",
    ]
    for duplicate in duplicates:
        team_id = str(duplicate.get("team_id") or duplicate.get("normalized_id") or "")
        lines.append(f'id "{team_id}" is declared by:')
        for team_file in duplicate.get("team_files", []):
            lines.append(f"- {team_file}")
        lines.append("")
    lines.append(
        "Rename one of these team.yaml ids, then restart webapp-studio."
        if blocked
        else "Rename one of these team.yaml ids to make the hidden teams selectable."
    )
    return "\n".join(lines)
