from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class AgentReference:
    id: str
    kind: str
    config: str
    entrypoint: bool

    @classmethod
    def from_mapping(cls, agent_id: str, value: Any) -> AgentReference:
        mapping = value if isinstance(value, dict) else {}
        return cls(
            id=agent_id,
            kind=mapping.get("kind", ""),
            config=mapping.get("config", ""),
            entrypoint=bool(mapping.get("entrypoint", False)),
        )

    def config_path(self, team_file: Path) -> Path:
        return (team_file.parent / self.config).resolve()
