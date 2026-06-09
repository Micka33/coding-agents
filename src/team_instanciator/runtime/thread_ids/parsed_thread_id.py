from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ParsedThreadId:
    version: str
    team_id: str
    conversation_id: str
    branch_id: str | None = None
    agent_id: str | None = None
    relations: tuple[tuple[str, str], ...] = ()
    relation_id: str | None = None
    target_agent_id: str | None = None
