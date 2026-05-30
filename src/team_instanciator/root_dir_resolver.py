from __future__ import annotations

from pathlib import Path

from src.team_loader.team_definition import TeamDefinition


class RootDirResolver:
    def resolve(self, team: TeamDefinition) -> Path:
        root = Path(team.defaults.root_dir)
        if root.is_absolute():
            return root
        return root.resolve()
