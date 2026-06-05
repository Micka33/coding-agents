from __future__ import annotations

from typing import TYPE_CHECKING

from src.type_defs import JsonMapping, JsonValue

from .conversation_branch import ConversationBranch
from .conversation_checkpoint_resume_result import ConversationCheckpointResumeResult
from .conversation_interrupt import ConversationInterrupt, ConversationInterruptDecision, ConversationInterruptKind
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

    def inject_agent_prompt(self, agent_id: str, content: str, *, wait: bool = True):
        return self._team.inject_agent_prompt(agent_id, content, wait=wait)

    def edit_human_message(
        self,
        event_id: str,
        content: str,
        *,
        author_id: str = "human",
        wait: bool = True,
    ):
        return self._team.edit_human_message(
            event_id,
            content,
            author_id=author_id,
            wait=wait,
        )

    def cancel_queued_agent(self, agent_id: str, *, branch_id: str | None = None) -> ConversationRuntimeStateDict:
        self._team.store.cancel_queued(agent_id, branch_id=branch_id)
        return self._team.store.get_runtime_state().to_dict()

    def clear_queue(self, scope: str = "pending") -> ConversationRuntimeStateDict:
        if scope in {"pending", "all"}:
            self._team.store.clear_pending_queue()
        return self._team.store.get_runtime_state().to_dict()

    def create_branch(
        self,
        *,
        label: str | None = None,
        origin_checkpoint_id: str | None = None,
        origin_event_id: str | None = None,
        origin_logical_message_id: str | None = None,
        origin_previous_event_id: str | None = None,
        origin_event_seq: int | None = None,
        head_checkpoint_id: str | None = None,
        parent_branch_id: str | None = None,
    ) -> ConversationBranch:
        return self._team.store.create_branch(
            label=label,
            origin_checkpoint_id=origin_checkpoint_id,
            origin_event_id=origin_event_id,
            origin_logical_message_id=origin_logical_message_id,
            origin_previous_event_id=origin_previous_event_id,
            origin_event_seq=origin_event_seq,
            head_checkpoint_id=head_checkpoint_id,
            parent_branch_id=parent_branch_id,
        )

    def list_branches(self) -> list[ConversationBranch]:
        return self._team.store.list_branches()

    def current_branch_id(self) -> str:
        return self._team.store.current_branch_id()

    def switch_branch(self, branch_id: str) -> ConversationBranch | None:
        return self._team.store.switch_branch(branch_id)

    def get_studio_branch_ui_state(self, *, participant_id: str = "human", branch_id: str | None = None):
        return self._team.store.get_studio_branch_ui_state(
            participant_id=participant_id,
            branch_id=branch_id,
        ).to_dict()

    def save_studio_branch_ui_state(
        self,
        *,
        participant_id: str = "human",
        branch_id: str | None = None,
        draft_content: str = "",
        outbox_state: JsonValue | None = None,
        editing_event_id: str | None = None,
        selected_agent_id: str | None = None,
        scroll_anchor_event_id: str | None = None,
    ):
        return self._team.store.save_studio_branch_ui_state(
            participant_id=participant_id,
            branch_id=branch_id,
            draft_content=draft_content,
            outbox_state=outbox_state,
            editing_event_id=editing_event_id,
            selected_agent_id=selected_agent_id,
            scroll_anchor_event_id=scroll_anchor_event_id,
        ).to_dict()

    def create_interrupt(
        self,
        *,
        kind: ConversationInterruptKind,
        payload: JsonMapping | None = None,
        run_id: str | None = None,
        agent_id: str | None = None,
        checkpoint_id: str | None = None,
        interrupt_id: str | None = None,
        branch_id: str | None = None,
    ) -> ConversationInterrupt:
        return self._team.store.create_interrupt(
            kind=kind,
            payload=payload,
            run_id=run_id,
            agent_id=agent_id,
            checkpoint_id=checkpoint_id,
            interrupt_id=interrupt_id,
            branch_id=branch_id,
        )

    def list_interrupts(self, *, active_only: bool = True, branch_id: str | None = None) -> list[ConversationInterrupt]:
        if branch_id is None:
            return self._team.store.list_interrupts(active_only=active_only)
        return self._team.store.list_interrupts(active_only=active_only, branch_id=branch_id)

    def resume_interrupt(
        self,
        interrupt_id: str,
        *,
        decision: ConversationInterruptDecision,
        response: str | None = None,
        edited_payload: JsonMapping | None = None,
        branch_id: str | None = None,
    ) -> ConversationInterrupt | None:
        if branch_id is None:
            return self._team.store.resume_interrupt(
                interrupt_id,
                decision=decision,
                response=response,
                edited_payload=edited_payload,
            )
        return self._team.store.resume_interrupt(
            interrupt_id,
            decision=decision,
            response=response,
            edited_payload=edited_payload,
            branch_id=branch_id,
        )

    def resume_checkpoint(
        self,
        *,
        checkpoint_id: str,
        checkpoint_ns: str,
        thread_id: str,
        mode: str = "resume",
        edited_content: str | None = None,
        origin_event_id: str | None = None,
        origin_event_seq: int | None = None,
    ) -> ConversationCheckpointResumeResult:
        return self._team.resume_checkpoint(
            checkpoint_id=checkpoint_id,
            checkpoint_ns=checkpoint_ns,
            thread_id=thread_id,
            mode=mode,
            edited_content=edited_content,
            origin_event_id=origin_event_id,
            origin_event_seq=origin_event_seq,
        )
