from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, TypedDict


ConversationRunStatus = Literal[
    "running",
    "success",
    "stopped",
    "failed",
    "empty",
    "interrupted",
    "cascade-limited",
    "skipped",
    "ignored",
]
CheckpointStability = Literal["stable", "unstable", "unknown"]
ConversationRunCommitState = Literal["pending", "committed", "orphaned"]


class ConversationRunDict(TypedDict):
    id: str
    team_id: str
    conversation_id: str
    branch_id: str
    agent_id: str
    logical_thread_key: str | None
    physical_thread_id: str | None
    status: ConversationRunStatus
    stop_kind: str | None
    snapshot_seq: int | None
    started_at: str
    completed_at: str | None
    stable_checkpoint_id: str | None
    latest_checkpoint_id: str | None
    checkpoint_stability: CheckpointStability
    usable_for_fork: bool
    usable_for_continue: bool
    commit_state: ConversationRunCommitState


@dataclass(frozen=True)
class ConversationRun:
    id: str
    team_id: str
    conversation_id: str
    branch_id: str
    agent_id: str
    status: ConversationRunStatus
    started_at: str
    logical_thread_key: str | None = None
    physical_thread_id: str | None = None
    stop_kind: str | None = None
    snapshot_seq: int | None = None
    completed_at: str | None = None
    stable_checkpoint_id: str | None = None
    latest_checkpoint_id: str | None = None
    checkpoint_stability: CheckpointStability = "unknown"
    usable_for_fork: bool = False
    usable_for_continue: bool = False
    commit_state: ConversationRunCommitState = "pending"

    def to_dict(self) -> ConversationRunDict:
        return {
            "id": self.id,
            "team_id": self.team_id,
            "conversation_id": self.conversation_id,
            "branch_id": self.branch_id,
            "agent_id": self.agent_id,
            "logical_thread_key": self.logical_thread_key,
            "physical_thread_id": self.physical_thread_id,
            "status": self.status,
            "stop_kind": self.stop_kind,
            "snapshot_seq": self.snapshot_seq,
            "started_at": self.started_at,
            "completed_at": self.completed_at,
            "stable_checkpoint_id": self.stable_checkpoint_id,
            "latest_checkpoint_id": self.latest_checkpoint_id,
            "checkpoint_stability": self.checkpoint_stability,
            "usable_for_fork": self.usable_for_fork,
            "usable_for_continue": self.usable_for_continue,
            "commit_state": self.commit_state,
        }
