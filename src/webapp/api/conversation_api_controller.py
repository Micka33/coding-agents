from __future__ import annotations

from typing import TypedDict
from urllib.parse import parse_qs

from src.type_defs import JsonObject
from src.team_instanciator.conversation.conversation_delivery import ConversationDeliveryDict
from src.team_instanciator.conversation.conversation_event import ConversationEventDict
from src.team_instanciator.conversation.payloads import ConversationStateDict
from src.webapp.attachments.attachment_ref_factory import AttachmentRefFactory
from src.webapp.api.conversation_protocol import WebConversation


class AppendMessageResponse(TypedDict):
    event: ConversationEventDict
    deliveries: list[ConversationDeliveryDict]
    failures: list[ConversationDeliveryDict]


class ConversationApiController:
    def __init__(self, conversation: WebConversation) -> None:
        self._conversation = conversation
        self._attachment_factory = AttachmentRefFactory(conversation)

    def state(self) -> ConversationStateDict:
        return self._conversation.state()

    def activity(self, query: str) -> ConversationStateDict:
        values = parse_qs(query)
        agent_id = values.get("agent_id", [None])[0]
        return self._conversation.activity(agent_id)

    def append_message(self, body: JsonObject) -> AppendMessageResponse:
        author_id = str(body.get("author_id") or "human")
        attachments = self._attachment_factory.refs(body.get("attachments") or [], author_id=author_id)
        result = self._conversation.append_human_message(
            str(body.get("content") or ""),
            author_id=author_id,
            files=attachments,
            wait=bool(body.get("wait", False)),
        )
        return {
            "event": result.event.to_dict(),
            "deliveries": [delivery.to_dict() for delivery in result.deliveries],
            "failures": [delivery.to_dict() for delivery in result.failures],
        }

    def update_runtime(self, body: JsonObject) -> ConversationStateDict:
        if "mention_hook_enabled" in body:
            self._conversation.runtime.set_mention_hook_enabled(bool(body["mention_hook_enabled"]))
        if "max_cascade_turns" in body:
            value = body["max_cascade_turns"]
            self._conversation.runtime.set_max_cascade_turns(None if value is None or value == "" else int(value))
        return self._conversation.state()

    def stop_agent(self, body: JsonObject) -> ConversationStateDict:
        agent_id = str(body.get("agent_id") or "")
        if not agent_id:
            raise ValueError("agent_id is required")
        self._conversation.runtime.stop_agent(agent_id)
        return self._conversation.state()
