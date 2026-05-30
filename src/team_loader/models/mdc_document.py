from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from src.type_defs import JsonObject


@dataclass(frozen=True)
class MdcDocument:
    path: Path
    frontmatter: JsonObject
    body: str
