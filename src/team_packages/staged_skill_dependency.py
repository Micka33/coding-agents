from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class StagedSkillDependency:
    skill_id: str
    repo_url: str
    requested: str | None
    resolved: str
    source_dir: Path
