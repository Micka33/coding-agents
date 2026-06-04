from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ParsedRelationThreadId:
    parent_thread_id: str
    relation_id: str
    target_agent_id: str
    source_agent_id: str | None = None
    tool_name: str | None = None
