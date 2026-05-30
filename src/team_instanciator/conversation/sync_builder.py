from __future__ import annotations

from langchain_core.messages import HumanMessage, SystemMessage

from src.team_loader.models.agent_definition import AgentDefinition

from .agent_delivery_state import AgentDeliveryState
from .agent_sync import AgentSync
from .conversation_delivery_error import ConversationDeliveryError
from .conversation_event import ConversationEvent
from .conversation_file_ref import ConversationFileRef


class AgentSyncBuilder:
    def __init__(self, *, identity_refresh_after_tokens: int = 10_000, max_delta_tokens: int | None = None) -> None:
        self._identity_refresh_after_tokens = identity_refresh_after_tokens
        self._max_delta_tokens = max_delta_tokens

    def build(
        self,
        *,
        target: AgentDefinition,
        state: AgentDeliveryState,
        events: list[ConversationEvent],
    ) -> AgentSync:
        if not events:
            return AgentSync(
                messages=[],
                snapshot_seq=state.last_delivered_seq,
                token_estimate=0,
                identity_inserted=False,
                projected_event_count=0,
            )

        token_estimate = sum(self._token_estimate(event.content) for event in events)
        if self._max_delta_tokens is not None and token_estimate > self._max_delta_tokens:
            raise ConversationDeliveryError(
                f"Undelivered conversation delta for '{target.id}' is estimated at {token_estimate} tokens, "
                f"above the configured limit of {self._max_delta_tokens}."
            )

        identity_inserted = self._should_insert_identity(state)
        messages: list[object] = []
        if identity_inserted:
            messages.append(SystemMessage(content=self._identity_text(target)))

        projected_event_count = 0
        for event in events:
            if event.author_id == target.id:
                continue
            projected_event_count += 1
            additional_kwargs = {"conversation_seq": event.seq}
            if event.attachments:
                additional_kwargs["attachments"] = [
                    self._attachment_payload(event, attachment)
                    for attachment in event.attachments
                ]
            messages.append(
                HumanMessage(
                    name=event.author_id,
                    content=event.content,
                    additional_kwargs=additional_kwargs,
                    response_metadata={"conversation_seq": event.seq, "conversation_event_id": event.id},
                )
            )

        return AgentSync(
            messages=messages,
            snapshot_seq=max(event.seq for event in events),
            token_estimate=token_estimate,
            identity_inserted=identity_inserted,
            projected_event_count=projected_event_count,
        )

    def _should_insert_identity(self, state: AgentDeliveryState) -> bool:
        return (
            state.last_identity_refresh_seq == 0
            or state.token_estimate_since_identity_refresh >= self._identity_refresh_after_tokens
        )

    def _identity_text(self, target: AgentDefinition) -> str:
        return (
            f"You are {target.id} ({target.name}). Other participants refer to you as @{target.id}.\n"
            "Public conversation updates from other participants are delivered as "
            'HumanMessage(name="<author-id>").\n'
            "Human-added public conversation files are included as attachments when you are mentioned."
        )

    def _attachment_payload(self, event: ConversationEvent, attachment: ConversationFileRef) -> dict[str, object]:
        payload = attachment.to_dict()
        if str(payload.get("uri") or "").startswith("conversation://files/"):
            payload["read_path"] = f"/.coding-agents/conversations/{event.conversation_id}/files/{attachment.id}"
        return payload

    def _token_estimate(self, content: str) -> int:
        return max(1, len(content) // 4) if content else 0
