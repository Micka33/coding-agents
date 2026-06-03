from __future__ import annotations

from dataclasses import dataclass

from .conversation_branch import ConversationBranch
from .conversation_event import ConversationEvent


@dataclass
class ConversationCheckpointResumeResult:
    branch: ConversationBranch
    event: ConversationEvent
    mode: str
