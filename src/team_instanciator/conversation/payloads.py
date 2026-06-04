from __future__ import annotations

from typing import NotRequired, TypedDict

from src.type_defs import JsonValue

from .agent_delivery_state import AgentDeliveryStateDict
from .conversation_branch_thread import ConversationBranchThreadDict
from .conversation_control_event import ConversationControlEventDict
from .conversation_delivery import ConversationDeliveryDict
from .conversation_event import ConversationEventDict
from .conversation_run import ConversationRunDict
from .conversation_runtime_state import ConversationRuntimeStateDict
from .external_side_effect import ExternalSideEffectDict
from .thread_frontier import ThreadFrontierDict


class MessageSummaryDict(TypedDict):
    type: str
    name: str | None
    content: str
    tool_calls: JsonValue
    created_at: NotRequired[str]


class ConversationStateDict(TypedDict):
    team_id: str
    conversation_id: str
    participants: list[str]
    participant_aliases: NotRequired[dict[str, list[str]]]
    runtime: ConversationRuntimeStateDict
    events: list[ConversationEventDict]
    agent_states: list[AgentDeliveryStateDict]
    deliveries: list[ConversationDeliveryDict]
    runs: list[ConversationRunDict]
    branch_threads: list[ConversationBranchThreadDict]
    thread_frontiers: list[ThreadFrontierDict]
    control_events: list[ConversationControlEventDict]
    external_side_effects: list[ExternalSideEffectDict]
    activities: list[AgentDeliveryStateDict]
    activity: AgentDeliveryStateDict | None
    private_thread_id: NotRequired[str]
    private_messages: NotRequired[list[MessageSummaryDict]]
