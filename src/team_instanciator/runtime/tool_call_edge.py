from __future__ import annotations

from dataclasses import dataclass
from typing import Literal


ToolCallEdgeStatus = Literal["running", "success", "failed"]


@dataclass(frozen=True)
class ToolCallEdge:
    id: str
    commit_id: str
    branch_id: str
    parent_logical_thread_key: str
    parent_physical_thread_id: str
    relation_id: str
    target_agent_id: str
    child_logical_thread_key: str
    child_physical_thread_id: str
    run_id: str | None
    status: ToolCallEdgeStatus
