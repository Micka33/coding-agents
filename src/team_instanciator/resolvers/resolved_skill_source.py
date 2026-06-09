from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class ResolvedSkillSource:
    host_path: Path
    virtual_path: str
    label: str
    allowed_skill_ids: tuple[str, ...] | None = None

    @property
    def deepagents_source(self) -> tuple[str, str]:
        return (self.virtual_path, self.label)
