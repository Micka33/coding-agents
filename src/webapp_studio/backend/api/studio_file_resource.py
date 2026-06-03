from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass
class StudioFileResource:
    path: Path
    filename: str
    media_type: str | None
