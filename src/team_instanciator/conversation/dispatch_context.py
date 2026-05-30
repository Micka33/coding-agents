from __future__ import annotations

from dataclasses import dataclass


@dataclass
class DispatchContext:
    cascade_turns: int = 0
