from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, TypedDict


ThreadFrontierBoundary = Literal["before", "after"]


class ThreadFrontierDict(TypedDict):
    frontier_id: str
    team_id: str
    conversation_id: str
    branch_id: str
    event_id: str
    event_boundary: ThreadFrontierBoundary
    logical_thread_key: str
    physical_thread_id: str
    checkpoint_id: str | None
    parent_logical_thread_key: str | None
    usable_for_fork: bool
    usable_for_continue: bool
    created_at: str


@dataclass(frozen=True)
class ThreadFrontier:
    frontier_id: str
    team_id: str
    conversation_id: str
    branch_id: str
    event_id: str
    event_boundary: ThreadFrontierBoundary
    logical_thread_key: str
    physical_thread_id: str
    checkpoint_id: str | None
    parent_logical_thread_key: str | None = None
    usable_for_fork: bool = False
    usable_for_continue: bool = False
    created_at: str = ""

    def to_dict(self) -> ThreadFrontierDict:
        return {
            "frontier_id": self.frontier_id,
            "team_id": self.team_id,
            "conversation_id": self.conversation_id,
            "branch_id": self.branch_id,
            "event_id": self.event_id,
            "event_boundary": self.event_boundary,
            "logical_thread_key": self.logical_thread_key,
            "physical_thread_id": self.physical_thread_id,
            "checkpoint_id": self.checkpoint_id,
            "parent_logical_thread_key": self.parent_logical_thread_key,
            "usable_for_fork": self.usable_for_fork,
            "usable_for_continue": self.usable_for_continue,
            "created_at": self.created_at,
        }
