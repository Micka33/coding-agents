from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class MemoryDefault:
    error_when_missing: bool
    candidates: tuple[str, ...]

    @classmethod
    def from_mapping(cls, value: Any) -> MemoryDefault:
        mapping = value if isinstance(value, dict) else {}
        candidates = mapping.get("candidates", ())
        return cls(
            error_when_missing=bool(mapping.get("error_when_missing", False)),
            candidates=tuple(candidates if isinstance(candidates, list) else ()),
        )
