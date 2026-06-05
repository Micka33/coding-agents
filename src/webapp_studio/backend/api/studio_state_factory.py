from __future__ import annotations

from typing import Any

from pydantic import ValidationError

from src.team_instanciator.conversation.conversation_branch import ConversationBranch
from src.team_instanciator.conversation.conversation_interrupt import ConversationInterrupt
from src.team_instanciator.conversation.payloads import ConversationStateDict
from src.webapp_studio.backend.api.time_utils import utc_now_iso
from src.webapp_studio.backend.contracts.activity_snapshot import ActivitySnapshot
from src.webapp_studio.backend.contracts.agent_delivery_state_dto import AgentDeliveryStateDto
from src.webapp_studio.backend.contracts.branch_summary import BranchSummary
from src.webapp_studio.backend.contracts.checkpoint_summary import CheckpointSummary
from src.webapp_studio.backend.contracts.conversation_branch_thread_dto import ConversationBranchThreadDto
from src.webapp_studio.backend.contracts.conversation_control_event_dto import ConversationControlEventDto
from src.webapp_studio.backend.contracts.conversation_delivery_dto import ConversationDeliveryDto
from src.webapp_studio.backend.contracts.conversation_event_dto import ConversationEventDto
from src.webapp_studio.backend.contracts.conversation_run_dto import ConversationRunDto
from src.webapp_studio.backend.contracts.conversation_snapshot import ConversationSnapshot
from src.webapp_studio.backend.contracts.external_side_effect_dto import ExternalSideEffectDto
from src.webapp_studio.backend.contracts.generated_ui_spec import GeneratedUiSpec
from src.webapp_studio.backend.contracts.history_snapshot import HistorySnapshot
from src.webapp_studio.backend.contracts.interrupt_request import InterruptRequest
from src.webapp_studio.backend.contracts.message_summary_dto import MessageSummaryDto
from src.webapp_studio.backend.contracts.private_thread_dto import PrivateThreadDto
from src.webapp_studio.backend.contracts.queue_item import QueueItem
from src.webapp_studio.backend.contracts.run_summary import RunSummary
from src.webapp_studio.backend.contracts.runtime_settings import RuntimeSettings
from src.webapp_studio.backend.contracts.studio_state import StudioState
from src.webapp_studio.backend.contracts.thread_frontier_dto import ThreadFrontierDto


class StudioStateFactory:
    def from_legacy_state(
        self,
        state: ConversationStateDict,
        *,
        checkpoints: list[CheckpointSummary] | None = None,
        branches: list[ConversationBranch] | None = None,
        interrupts: list[ConversationInterrupt] | None = None,
        current_branch_id: str = "branch_main",
        dismissed_failed_queue_delivery_ids: set[str] | None = None,
        private_activity_states: list[ConversationStateDict] | None = None,
    ) -> StudioState:
        branch_list = branches or []
        visible_state = self._visible_state(state, branch_list, current_branch_id)
        agent_states = [AgentDeliveryStateDto.model_validate(item) for item in visible_state.get("agent_states", [])]
        deliveries = [ConversationDeliveryDto.model_validate(item) for item in visible_state.get("deliveries", [])]
        conversation = ConversationSnapshot(
            events=[ConversationEventDto.model_validate(item) for item in visible_state.get("events", [])],
            deliveries=deliveries,
            runs=[ConversationRunDto.model_validate(item) for item in visible_state.get("runs", [])],
            agent_states=agent_states,
            branch_threads=[ConversationBranchThreadDto.model_validate(item) for item in visible_state.get("branch_threads", [])],
            thread_frontiers=[ThreadFrontierDto.model_validate(item) for item in visible_state.get("thread_frontiers", [])],
            control_events=[ConversationControlEventDto.model_validate(item) for item in visible_state.get("control_events", [])],
            external_side_effects=[ExternalSideEffectDto.model_validate(item) for item in visible_state.get("external_side_effects", [])],
        )
        checkpoint_list = checkpoints or []
        history = HistorySnapshot(
            current_branch_id=current_branch_id,
            checkpoints=checkpoint_list,
            branches=[
                self._main_branch(state, checkpoint_list, current_branch_id=current_branch_id),
                *[self._branch_summary(branch, current_branch_id=current_branch_id) for branch in branch_list],
            ],
        )
        return StudioState(
            team_id=state["team_id"],
            conversation_id=state["conversation_id"],
            participants=list(state.get("participants", [])),
            participant_aliases=dict(state.get("participant_aliases", {})),
            runtime=RuntimeSettings.model_validate(state["runtime"]),
            conversation=conversation,
            activity=self._activity(state, agent_states, private_activity_states or []),
            runs=self._runs(state, agent_states, deliveries),
            queue=self._queue(state, agent_states, deliveries, dismissed_failed_queue_delivery_ids or set()),
            interrupts=[self._interrupt_request(interrupt) for interrupt in interrupts or []],
            history=history,
            generated_ui=self._generated_ui(visible_state),
        )

    def _activity(
        self,
        state: ConversationStateDict,
        agent_states: list[AgentDeliveryStateDto],
        private_activity_states: list[ConversationStateDict],
    ) -> ActivitySnapshot:
        active_agent_ids = [item.agent_id for item in agent_states if item.running or item.queued]
        private_threads = []
        seen_thread_ids = set()
        for activity_state in [state, *private_activity_states]:
            thread_id = activity_state.get("private_thread_id")
            if not thread_id:
                continue
            thread_id_value = str(thread_id)
            if thread_id_value in seen_thread_ids:
                continue
            seen_thread_ids.add(thread_id_value)
            private_threads.append(
                PrivateThreadDto(
                    agent_id=self._agent_id_from_thread(thread_id_value),
                    thread_id=thread_id_value,
                    messages=[MessageSummaryDto.model_validate(item) for item in activity_state.get("private_messages", [])],
                )
            )
        return ActivitySnapshot(active_agent_ids=active_agent_ids, private_threads=private_threads)

    def _runs(
        self,
        state: ConversationStateDict,
        agent_states: list[AgentDeliveryStateDto],
        deliveries: list[ConversationDeliveryDto],
    ) -> list[RunSummary]:
        runs = []
        cursor = self._latest_event_cursor(state)
        active_run_ids = set()
        persisted_runs = [ConversationRunDto.model_validate(item) for item in state.get("runs", [])]
        for run in reversed(persisted_runs):
            active_run_ids.add(run.id)
            runs.append(
                RunSummary(
                    id=run.id,
                    conversation_id=run.conversation_id,
                    agent_id=run.agent_id,
                    status=self._run_status_from_persisted(run.status, run.commit_state),
                    created_at=run.started_at,
                    updated_at=run.completed_at or run.started_at,
                    completed_at=run.completed_at,
                    checkpoint_id=run.stable_checkpoint_id,
                    cursor=cursor,
                    metadata={
                        "branch_id": run.branch_id,
                        "logical_thread_key": run.logical_thread_key,
                        "physical_thread_id": run.physical_thread_id,
                        "latest_checkpoint_id": run.latest_checkpoint_id,
                        "checkpoint_stability": run.checkpoint_stability,
                        "usable_for_fork": run.usable_for_fork,
                        "usable_for_continue": run.usable_for_continue,
                        "commit_state": run.commit_state,
                        "snapshot_seq": run.snapshot_seq,
                    },
                )
            )
        for item in agent_states:
            if item.current_run_id:
                if item.current_run_id in active_run_ids:
                    continue
                active_run_ids.add(item.current_run_id)
                runs.append(
                    RunSummary(
                        id=item.current_run_id,
                        conversation_id=item.conversation_id,
                        agent_id=item.agent_id,
                        status="running" if item.running else "queued" if item.queued else "unknown",
                        cursor=cursor,
                        metadata={"branch_id": item.branch_id, "current_snapshot_seq": item.current_snapshot_seq},
                    )
                )
        for delivery in reversed(deliveries):
            if delivery.run_id is None or delivery.run_id in active_run_ids:
                continue
            active_run_ids.add(delivery.run_id)
            runs.append(
                RunSummary(
                    id=delivery.run_id,
                    conversation_id=delivery.conversation_id,
                    agent_id=delivery.agent_id,
                    status=self._run_status_from_delivery(delivery.status),
                    created_at=delivery.created_at,
                    updated_at=delivery.completed_at or delivery.created_at,
                    completed_at=delivery.completed_at,
                    cursor=cursor,
                    metadata={
                        "delivery_id": delivery.id,
                        "branch_id": delivery.branch_id,
                        "delivery_status": delivery.status,
                        "error": delivery.error,
                        "snapshot_seq": delivery.snapshot_seq,
                    },
                )
            )
        return runs

    def _run_status_from_persisted(self, status: str, commit_state: str) -> str:
        if commit_state == "orphaned":
            return "unknown"
        if status == "running":
            return "running"
        if status in {"failed", "empty", "cascade-limited", "interrupted"}:
            return "failed"
        if status == "stopped":
            return "stopped"
        if status == "ignored":
            return "superseded"
        return "completed"

    def _run_status_from_delivery(self, status: str) -> str:
        if status in {"failed", "empty", "interrupted", "cascade-limited"}:
            return "failed"
        if status == "stopped":
            return "stopped"
        if status == "ignored":
            return "superseded"
        return "completed"

    def _queue(
        self,
        state: ConversationStateDict,
        agent_states: list[AgentDeliveryStateDto],
        deliveries: list[ConversationDeliveryDto],
        dismissed_failed_queue_delivery_ids: set[str],
    ) -> list[QueueItem]:
        queued = [item for item in agent_states if item.queued]
        pending = [
            QueueItem(
                id=f"queue_{state['conversation_id']}_{item.agent_id}",
                conversation_id=item.conversation_id,
                branch_id=item.branch_id,
                agent_id=item.agent_id,
                status="pending",
                position=index,
                message_event_id=self._event_id_for_seq(state, item.queued_after_seq),
                can_cancel=not item.running,
            )
            for index, item in enumerate(queued, start=1)
        ]
        failed = [
            QueueItem(
                id=f"queue_failed_{delivery.id}",
                conversation_id=delivery.conversation_id,
                branch_id=delivery.branch_id,
                agent_id=delivery.agent_id,
                status="failed",
                position=None,
                enqueued_at=delivery.created_at,
                updated_at=delivery.completed_at or delivery.created_at,
                message_event_id=self._event_id_for_seq(state, delivery.snapshot_seq),
                can_cancel=False,
                error=delivery.error,
            )
            for delivery in reversed(deliveries)
            if delivery.status in {"failed", "empty", "cascade-limited"} and delivery.id not in dismissed_failed_queue_delivery_ids
        ]
        return [*pending, *failed]

    def _interrupt_request(self, interrupt: ConversationInterrupt) -> InterruptRequest:
        return InterruptRequest(
            id=interrupt.id,
            branch_id=interrupt.branch_id,
            run_id=interrupt.run_id,
            agent_id=interrupt.agent_id,
            checkpoint_id=interrupt.checkpoint_id,
            created_at=interrupt.created_at,
            kind=interrupt.kind,
            payload=interrupt.payload,
            status=interrupt.status,
            decisions=list(interrupt.decisions),
        )

    def _main_branch(
        self,
        state: ConversationStateDict,
        checkpoints: list[CheckpointSummary],
        *,
        current_branch_id: str,
    ) -> BranchSummary:
        return BranchSummary(
            id="branch_main",
            label="Main",
            created_at=self._first_event_time(state),
            current=current_branch_id == "branch_main",
            status="derived",
            head_checkpoint_id=checkpoints[-1].id if checkpoints else None,
        )

    def _branch_summary(self, branch: ConversationBranch, *, current_branch_id: str) -> BranchSummary:
        return BranchSummary(
            id=branch.id,
            label=branch.label,
            parent_branch_id=branch.parent_branch_id,
            origin_checkpoint_id=branch.origin_checkpoint_id,
            origin_event_id=branch.origin_event_id,
            origin_event_seq=branch.origin_event_seq,
            created_at=branch.created_at,
            current=branch.current or branch.id == current_branch_id,
            status=branch.status,
            head_checkpoint_id=branch.head_checkpoint_id,
        )

    def _visible_state(
        self,
        state: ConversationStateDict,
        branches: list[ConversationBranch],
        current_branch_id: str,
    ) -> ConversationStateDict:
        visible = dict(state)
        visible["events"] = self._visible_events(state, branches, current_branch_id)
        return visible

    def _visible_events(
        self,
        state: ConversationStateDict,
        branches: list[ConversationBranch],
        current_branch_id: str,
    ) -> list[dict[str, Any]]:
        events: list[dict[str, Any]] = state.get("events", [])
        if current_branch_id == "branch_main":
            return [event for event in events if self._event_branch_id(event) == "branch_main"]
        branch = next((item for item in branches if item.id == current_branch_id), None)
        origin_seq = branch.origin_event_seq if branch is not None else None
        visible = []
        for event in events:
            branch_id = self._event_branch_id(event)
            if branch_id == current_branch_id:
                visible.append(event)
            elif branch_id == "branch_main" and (origin_seq is None or int(event.get("seq") or 0) <= origin_seq):
                visible.append(event)
        return visible

    def _event_branch_id(self, event: dict[str, Any]) -> str:
        branch_id = event.get("branch_id")
        if branch_id:
            return str(branch_id)
        metadata = event.get("metadata", {})
        metadata_branch_id = metadata.get("branch_id") if isinstance(metadata, dict) else None
        return str(metadata_branch_id) if metadata_branch_id else "branch_main"

    def _generated_ui(self, state: ConversationStateDict) -> list[GeneratedUiSpec]:
        specs: dict[str, GeneratedUiSpec] = {}
        for event in state.get("events", []):
            metadata = event.get("metadata", {})
            if not isinstance(metadata, dict):
                continue
            for candidate in self._generated_ui_candidates(metadata):
                if not isinstance(candidate, dict):
                    continue
                try:
                    spec = GeneratedUiSpec.model_validate(candidate)
                except ValidationError:
                    continue
                specs[spec.id] = spec
        return list(specs.values())

    def _generated_ui_candidates(self, metadata: dict[str, Any]) -> list[Any]:
        candidates = []
        for key in ("generated_ui", "generated_ui_spec"):
            value = metadata.get(key)
            if value is not None:
                candidates.append(value)
        listed = metadata.get("generated_ui_specs")
        if isinstance(listed, list):
            candidates.extend(listed)
        return candidates

    def _first_event_time(self, state: ConversationStateDict) -> str:
        events: list[dict[str, Any]] = state.get("events", [])
        if events:
            return str(events[0].get("created_at") or utc_now_iso())
        return utc_now_iso()

    def _latest_event_cursor(self, state: ConversationStateDict) -> str | None:
        events: list[dict[str, Any]] = state.get("events", [])
        if not events:
            return None
        return f"event_seq:{max(int(event.get('seq') or 0) for event in events)}"

    def _event_id_for_seq(self, state: ConversationStateDict, seq: int | None) -> str | None:
        if seq is None:
            return None
        for event in state.get("events", []):
            if event.get("seq") == seq:
                return str(event.get("id"))
        return None

    def _agent_id_from_thread(self, thread_id: str) -> str | None:
        marker = ":mention:"
        if marker not in thread_id:
            return None
        return thread_id.rsplit(marker, maxsplit=1)[-1] or None
