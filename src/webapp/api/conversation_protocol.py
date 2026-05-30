from __future__ import annotations

from collections.abc import Iterable
from typing import Protocol, TypeAlias

from src.type_defs import JsonObject
from src.team_instanciator.conversation.conversation_append_result import ConversationAppendResult
from src.team_instanciator.conversation.conversation_file_ref import ConversationFileRef
from src.team_instanciator.conversation.conversation_runtime_state import ConversationRuntimeStateDict
from src.team_instanciator.conversation.payloads import ConversationStateDict

AttachmentInput: TypeAlias = ConversationFileRef | JsonObject


class WebConversationRuntime(Protocol):
    def set_mention_hook_enabled(self, enabled: bool) -> ConversationRuntimeStateDict:
        ...

    def set_max_cascade_turns(self, value: int | None) -> ConversationRuntimeStateDict:
        ...

    def stop_agent(self, agent_id: str) -> None:
        ...


class WebConversation(Protocol):
    runtime: WebConversationRuntime

    def state(self) -> ConversationStateDict:
        ...

    def activity(self, agent_id: str | None = None) -> ConversationStateDict:
        ...

    def append_human_message(
        self,
        content: str,
        *,
        author_id: str = "human",
        files: Iterable[AttachmentInput] | None = None,
        wait: bool = True,
    ) -> ConversationAppendResult:
        ...

    def create_public_file_ref(
        self,
        *,
        filename: str,
        content: bytes,
        added_by: str,
        media_type: str | None = None,
    ) -> ConversationFileRef:
        ...
