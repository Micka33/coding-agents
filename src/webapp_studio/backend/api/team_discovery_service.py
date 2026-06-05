from __future__ import annotations

from pathlib import Path
from typing import Any

from src.team_loader.parsing.yaml_parser import YamlParser
from src.type_defs import is_json_object


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
        for team_file, source in self._candidate_files(explicit_team_file):
            resolved = team_file.expanduser().resolve()
            if resolved in seen_paths:
                continue
            seen_paths.add(resolved)
            descriptor = self._descriptor(resolved, source)
            if descriptor is not None and descriptor["conversation_available"]:
                teams.append(descriptor)

        duplicate_ids = self._duplicate_ids(teams)
        return {
            "status": "blocked" if duplicate_ids else "ready",
            "teams": [] if duplicate_ids else teams,
            "duplicate_ids": duplicate_ids,
        }

    def _candidate_files(self, explicit_team_file: str | Path | None) -> list[tuple[Path, str]]:
        candidates: list[tuple[Path, str]] = []
        if explicit_team_file is not None:
            candidates.append((Path(explicit_team_file), "explicit"))
        candidates.extend(
            (path, "project")
            for path in sorted((self._workspace_dir / ".coding-agents" / "teams").glob("*/team.yaml"))
        )
        candidates.extend(
            (path, "builtin")
            for path in sorted((self._repository_root / "teams").glob("*/team.yaml"))
        )
        return candidates

    def _descriptor(self, team_file: Path, source: str) -> dict[str, Any] | None:
        if not team_file.is_file():
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
            "team_id": str(team_id),
            "description": str(description) if description is not None else None,
            "team_file": str(team_file),
            "source": source,
            "conversation_available": "conversation" in parsed,
            "participants": participants,
            "participant_aliases": self._participant_aliases(parsed, participants),
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


def duplicate_team_id_message(discovery: dict[str, Any]) -> str | None:
    duplicates = discovery.get("duplicate_ids")
    if not isinstance(duplicates, list) or not duplicates:
        return None
    lines = ["Studio team discovery failed: duplicate team ids.", ""]
    for duplicate in duplicates:
        team_id = str(duplicate.get("team_id") or duplicate.get("normalized_id") or "")
        lines.append(f'id "{team_id}" is declared by:')
        for team_file in duplicate.get("team_files", []):
            lines.append(f"- {team_file}")
        lines.append("")
    lines.append("Rename one of these team.yaml ids, then restart webapp-studio.")
    return "\n".join(lines)
