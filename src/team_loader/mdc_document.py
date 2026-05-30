from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class MdcDocument:
    path: Path
    frontmatter: dict[str, Any]
    body: str
