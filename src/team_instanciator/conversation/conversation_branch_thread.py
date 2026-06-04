from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, TypedDict


BranchThreadStatus = Literal["active", "orphaned"]


class ConversationBranchThreadDict(TypedDict):
    team_id: str
    conversation_id: str
    branch_id: str
    logical_thread_key: str
    physical_thread_id: str
    forked_from_branch_id: str | None
    forked_from_thread_id: str | None
    forked_from_checkpoint_id: str | None
    created_by_commit_id: str | None
    status: BranchThreadStatus


@dataclass(frozen=True)
class ConversationBranchThread:
    team_id: str
    conversation_id: str
    branch_id: str
    logical_thread_key: str
    physical_thread_id: str
    forked_from_branch_id: str | None = None
    forked_from_thread_id: str | None = None
    forked_from_checkpoint_id: str | None = None
    created_by_commit_id: str | None = None
    status: BranchThreadStatus = "active"

    def to_dict(self) -> ConversationBranchThreadDict:
        return {
            "team_id": self.team_id,
            "conversation_id": self.conversation_id,
            "branch_id": self.branch_id,
            "logical_thread_key": self.logical_thread_key,
            "physical_thread_id": self.physical_thread_id,
            "forked_from_branch_id": self.forked_from_branch_id,
            "forked_from_thread_id": self.forked_from_thread_id,
            "forked_from_checkpoint_id": self.forked_from_checkpoint_id,
            "created_by_commit_id": self.created_by_commit_id,
            "status": self.status,
        }
