from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ParsedRelationThreadId:
    parent_thread_id: str
    source_agent_id: str
    tool_name: str
    target_agent_id: str
