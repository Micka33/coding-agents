from __future__ import annotations

from typing import TYPE_CHECKING

from .conversation_runtime_state import ConversationRuntimeStateDict

if TYPE_CHECKING:
    from .team import MentionAwareTeam


class ConversationRuntimeController:
    def __init__(self, team: MentionAwareTeam) -> None:
        self._team = team

    def set_mention_hook_enabled(self, enabled: bool) -> ConversationRuntimeStateDict:
        return self._team.store.update_runtime_state(mention_hook_enabled=enabled).to_dict()

    def set_max_cascade_turns(self, value: int | None) -> ConversationRuntimeStateDict:
        if value is not None and value < 1:
            raise ValueError("max_cascade_turns must be null or positive.")
        return self._team.store.update_runtime_state(max_cascade_turns=value).to_dict()

    def stop_agent(self, agent_id: str) -> None:
        self._team.router.stop(agent_id)
