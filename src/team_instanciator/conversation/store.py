from __future__ import annotations

import json
import sqlite3
import threading
import uuid
from dataclasses import replace
from datetime import datetime, timezone
from typing import cast

from src.type_defs import JsonMapping, JsonObject, JsonValue, is_json_object, is_json_value
from src.team_instanciator.runtime.tool_call_edge import ToolCallEdge, ToolCallEdgeStatus
from src.team_instanciator.runtime.thread_forker import ThreadForker

from .agent_delivery_state import AgentDeliveryState
from .conversation_branch_thread import BranchThreadStatus, ConversationBranchThread
from .conversation_branch import ConversationBranch
from .conversation_control_event import ConversationControlEvent
from .conversation_delivery import ConversationDelivery, DeliveryStatus
from .conversation_event import AuthorKind, ConversationEvent
from .conversation_file_ref import ConversationFileRef
from .conversation_interrupt import (
    ConversationInterrupt,
    ConversationInterruptDecision,
    ConversationInterruptKind,
    ConversationInterruptStatus,
)
from .conversation_model_attempt import ConversationModelAttempt, ModelAttemptStatus
from .conversation_run import (
    CheckpointStability,
    ConversationRun,
    ConversationRunCommitState,
    ConversationRunStatus,
)
from .conversation_runtime_state import ConversationRuntimeState
from .external_side_effect import ExternalSideEffect
from .studio_branch_ui_state import StudioBranchUiState
from .thread_frontier import ThreadFrontier, ThreadFrontierBoundary


class _UnsetType:
    pass


_UNSET = _UnsetType()
_DELIVERY_STATUSES: tuple[DeliveryStatus, ...] = (
    "cascade-limited",
    "empty",
    "failed",
    "ignored",
    "interrupted",
    "skipped",
    "stopped",
    "success",
)
_INTERRUPT_DECISIONS: tuple[ConversationInterruptDecision, ...] = ("approve", "reject", "edit", "respond")
_INTERRUPT_KINDS: tuple[ConversationInterruptKind, ...] = ("approve", "edit", "respond", "review")
_INTERRUPT_STATUSES: tuple[ConversationInterruptStatus, ...] = ("pending", "resolved")
_BRANCH_THREAD_STATUSES: tuple[BranchThreadStatus, ...] = ("active", "orphaned")
_THREAD_FRONTIER_BOUNDARIES: tuple[ThreadFrontierBoundary, ...] = ("before", "after")
_RUN_STATUSES: tuple[ConversationRunStatus, ...] = (
    "running",
    "success",
    "stopped",
    "failed",
    "empty",
    "interrupted",
    "cascade-limited",
    "skipped",
    "ignored",
)
_CHECKPOINT_STABILITIES: tuple[CheckpointStability, ...] = ("stable", "unstable", "unknown")
_RUN_COMMIT_STATES: tuple[ConversationRunCommitState, ...] = ("pending", "committed", "orphaned")
_MODEL_ATTEMPT_STATUSES: tuple[ModelAttemptStatus, ...] = ("running", "retrying", "success", "failed")
_HISTORY_SCHEMA_VERSION = "branching.v1"
ORPHANED_RUN_DELIVERY_ERROR = "Run was still pending when the backend restarted; no terminal delivery was recorded."


class ConversationStore:
    def __init__(
        self,
        *,
        team_id: str,
        conversation_id: str,
        connection: sqlite3.Connection | None = None,
        default_max_cascade_turns: int | None = None,
    ) -> None:
        self.team_id = team_id
        self.conversation_id = conversation_id
        self._connection = connection
        self._default_max_cascade_turns = default_max_cascade_turns
        self._lock = threading.RLock()
        self._events: list[ConversationEvent] = []
        self._agent_states: dict[tuple[str, str], AgentDeliveryState] = {}
        self._deliveries: list[ConversationDelivery] = []
        self._branches: dict[str, ConversationBranch] = {}
        self._branch_threads: dict[tuple[str, str], ConversationBranchThread] = {}
        self._thread_frontiers: list[ThreadFrontier] = []
        self._control_events: list[ConversationControlEvent] = []
        self._external_side_effects: list[ExternalSideEffect] = []
        self._studio_branch_ui_states: dict[tuple[str, str], StudioBranchUiState] = {}
        self._runs: dict[str, ConversationRun] = {}
        self._model_attempts: dict[str, ConversationModelAttempt] = {}
        self._interrupts: dict[str, ConversationInterrupt] = {}
        self._current_branch_id = "branch_main"
        self._runtime_state = ConversationRuntimeState(
            team_id=team_id,
            conversation_id=conversation_id,
            max_cascade_turns=default_max_cascade_turns,
        )
        if self._connection is not None:
            self._initialize_sqlite()

    def append_event(
        self,
        *,
        author_id: str,
        author_kind: AuthorKind,
        content: str,
        branch_id: str | None = None,
        logical_message_id: str | None = None,
        version_parent_event_id: str | None = None,
        parent_event_id: str | None = None,
        frontier_before_event_id: str | None = None,
        frontier_after_event_id: str | None = None,
        mentions: tuple[str, ...] = (),
        attachments: tuple[ConversationFileRef, ...] = (),
        source_thread_id: str | None = None,
        source_message_id: str | None = None,
        metadata: JsonMapping | None = None,
    ) -> ConversationEvent:
        with self._lock:
            seq = self._next_seq()
            event_id = f"evt_{uuid.uuid4().hex}"
            resolved_branch_id = self._resolved_branch_id(branch_id)
            previous_event = self._latest_visible_event(resolved_branch_id)
            resolved_frontier_before_event_id = (
                frontier_before_event_id
                if frontier_before_event_id is not None
                else (previous_event.frontier_after_event_id if previous_event is not None else None)
            )
            event = ConversationEvent(
                id=event_id,
                team_id=self.team_id,
                conversation_id=self.conversation_id,
                branch_id=resolved_branch_id,
                logical_message_id=logical_message_id or event_id,
                version_parent_event_id=version_parent_event_id,
                parent_event_id=parent_event_id,
                frontier_before_event_id=resolved_frontier_before_event_id,
                frontier_after_event_id=frontier_after_event_id or f"frontier_{event_id}_after",
                seq=seq,
                created_at=self._now(),
                author_id=author_id,
                author_kind="agent" if author_kind == "agent" else "human",
                content=content,
                mentions=tuple(mentions),
                attachments=tuple(attachments),
                source_thread_id=source_thread_id,
                source_message_id=source_message_id,
                metadata=metadata or {},
            )
            if self._connection is None:
                self._events.append(event)
                return event

            self._connection.execute(
                """
                insert into team_conversation_events (
                    team_id,
                    conversation_id,
                    branch_id,
                    logical_message_id,
                    version_parent_event_id,
                    parent_event_id,
                    frontier_before_event_id,
                    frontier_after_event_id,
                    seq,
                    id,
                    created_at,
                    author_id,
                    author_kind,
                    content,
                    mentions_json,
                    source_thread_id,
                    source_message_id,
                    metadata_json
                )
                values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    event.team_id,
                    event.conversation_id,
                    event.branch_id,
                    event.logical_message_id or event.id,
                    event.version_parent_event_id,
                    event.parent_event_id,
                    event.frontier_before_event_id,
                    event.frontier_after_event_id,
                    event.seq,
                    event.id,
                    event.created_at,
                    event.author_id,
                    event.author_kind,
                    event.content,
                    json.dumps(list(event.mentions), ensure_ascii=False),
                    event.source_thread_id,
                    event.source_message_id,
                    json.dumps(dict(event.metadata), ensure_ascii=False),
                ),
            )
            for attachment in event.attachments:
                self._connection.execute(
                    """
                    insert into team_conversation_files (
                        team_id,
                        conversation_id,
                        event_id,
                        file_id,
                        filename,
                        uri,
                        media_type,
                        size_bytes,
                        added_by
                    )
                    values (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        event.team_id,
                        event.conversation_id,
                        event.id,
                        attachment.id,
                        attachment.filename,
                        attachment.uri,
                        attachment.media_type,
                        attachment.size_bytes,
                        attachment.added_by,
                    ),
                )
            self._connection.commit()
            return event

    def list_events(
        self,
        *,
        after_seq: int = 0,
        through_seq: int | None = None,
        branch_id: str | None | _UnsetType = _UNSET,
    ) -> list[ConversationEvent]:
        with self._lock:
            resolved_branch_id = self.current_branch_id() if branch_id is _UNSET else branch_id
            if self._connection is None:
                return [
                    event
                    for event in self._events
                    if event.seq > after_seq and (through_seq is None or event.seq <= through_seq)
                    and self._event_visible_in_branch(event, resolved_branch_id)
                ]

            clauses = ["team_id = ?", "conversation_id = ?", "seq > ?"]
            params: list[object] = [self.team_id, self.conversation_id, after_seq]
            if through_seq is not None:
                clauses.append("seq <= ?")
                params.append(through_seq)
            rows = self._connection.execute(
                f"""
                select
                    team_id,
                    conversation_id,
                    branch_id,
                    logical_message_id,
                    version_parent_event_id,
                    parent_event_id,
                    frontier_before_event_id,
                    frontier_after_event_id,
                    seq,
                    id,
                    created_at,
                    author_id,
                    author_kind,
                    content,
                    mentions_json,
                    source_thread_id,
                    source_message_id,
                    metadata_json
                from team_conversation_events
                where {" and ".join(clauses)}
                order by seq asc
                """,
                tuple(params),
            ).fetchall()
            events = [self._event_from_row(row) for row in rows]
            return [event for event in events if self._event_visible_in_branch(event, resolved_branch_id)]

    def get_event(self, event_id: str) -> ConversationEvent | None:
        with self._lock:
            if self._connection is None:
                for event in self._events:
                    if event.id == event_id:
                        return replace(event)
                return None
            row = self._connection.execute(
                """
                select
                    team_id,
                    conversation_id,
                    branch_id,
                    logical_message_id,
                    version_parent_event_id,
                    parent_event_id,
                    frontier_before_event_id,
                    frontier_after_event_id,
                    seq,
                    id,
                    created_at,
                    author_id,
                    author_kind,
                    content,
                    mentions_json,
                    source_thread_id,
                    source_message_id,
                    metadata_json
                from team_conversation_events
                where team_id = ? and conversation_id = ? and id = ?
                """,
                (self.team_id, self.conversation_id, event_id),
            ).fetchone()
            return self._event_from_row(row) if row is not None else None

    def get_runtime_state(self) -> ConversationRuntimeState:
        with self._lock:
            if self._connection is None:
                return replace(self._runtime_state)
            row = self._connection.execute(
                """
                select mention_hook_enabled, max_cascade_turns
                from team_conversation_runtime_state
                where team_id = ? and conversation_id = ?
                """,
                (self.team_id, self.conversation_id),
            ).fetchone()
            if row is None:
                self._upsert_runtime_state(self._runtime_state)
                return replace(self._runtime_state)
            return ConversationRuntimeState(
                team_id=self.team_id,
                conversation_id=self.conversation_id,
                mention_hook_enabled=bool(row[0]),
                max_cascade_turns=row[1],
            )

    def update_runtime_state(
        self,
        *,
        mention_hook_enabled: bool | None = None,
        max_cascade_turns: int | None | _UnsetType = _UNSET,
    ) -> ConversationRuntimeState:
        with self._lock:
            state = self.get_runtime_state()
            updated = ConversationRuntimeState(
                team_id=state.team_id,
                conversation_id=state.conversation_id,
                mention_hook_enabled=state.mention_hook_enabled if mention_hook_enabled is None else mention_hook_enabled,
                max_cascade_turns=state.max_cascade_turns if max_cascade_turns is _UNSET else max_cascade_turns,
            )
            if self._connection is None:
                self._runtime_state = updated
            else:
                self._upsert_runtime_state(updated)
            return replace(updated)

    def ensure_agent_state(self, agent_id: str, *, branch_id: str | None = None) -> AgentDeliveryState:
        with self._lock:
            resolved_branch_id = self._resolved_branch_id(branch_id)
            state = self.get_agent_state(agent_id, branch_id=resolved_branch_id)
            if state is not None:
                return state
            state = AgentDeliveryState(
                team_id=self.team_id,
                conversation_id=self.conversation_id,
                branch_id=resolved_branch_id,
                agent_id=agent_id,
            )
            self.save_agent_state(state)
            return replace(state)

    def get_agent_state(self, agent_id: str, *, branch_id: str | None = None) -> AgentDeliveryState | None:
        with self._lock:
            resolved_branch_id = self._resolved_branch_id(branch_id)
            if self._connection is None:
                state = self._agent_states.get((resolved_branch_id, agent_id))
                return replace(state) if state is not None else None
            row = self._connection.execute(
                """
                select
                    branch_id,
                    last_delivered_seq,
                    running,
                    queued,
                    queued_after_seq,
                    current_run_id,
                    current_snapshot_seq,
                    stop_requested,
                    last_identity_refresh_seq,
                    token_estimate_since_identity_refresh
                from team_conversation_agent_state
                where team_id = ? and conversation_id = ? and branch_id = ? and agent_id = ?
                """,
                (self.team_id, self.conversation_id, resolved_branch_id, agent_id),
            ).fetchone()
            if row is None:
                return None
            return AgentDeliveryState(
                team_id=self.team_id,
                conversation_id=self.conversation_id,
                branch_id=str(row[0]),
                agent_id=agent_id,
                last_delivered_seq=int(row[1] or 0),
                running=bool(row[2]),
                queued=bool(row[3]),
                queued_after_seq=row[4],
                current_run_id=row[5],
                current_snapshot_seq=row[6],
                stop_requested=bool(row[7]),
                last_identity_refresh_seq=int(row[8] or 0),
                token_estimate_since_identity_refresh=int(row[9] or 0),
            )

    def list_agent_states(self, *, branch_id: str | None | _UnsetType = _UNSET) -> list[AgentDeliveryState]:
        with self._lock:
            resolved_branch_id = self.current_branch_id() if branch_id is _UNSET else branch_id
            if self._connection is None:
                states = [
                    state
                    for (state_branch_id, _agent_id), state in self._agent_states.items()
                    if resolved_branch_id is None or state_branch_id == resolved_branch_id
                ]
                return [replace(state) for state in sorted(states, key=lambda item: (item.branch_id, item.agent_id))]
            clauses = ["team_id = ?", "conversation_id = ?"]
            params: list[object] = [self.team_id, self.conversation_id]
            if resolved_branch_id is not None:
                clauses.append("branch_id = ?")
                params.append(resolved_branch_id)
            rows = self._connection.execute(
                f"""
                select branch_id, agent_id from team_conversation_agent_state
                where {" and ".join(clauses)}
                order by branch_id asc, agent_id asc
                """,
                tuple(params),
            ).fetchall()
            return [
                state
                for row in rows
                if (state := self.get_agent_state(str(row[1]), branch_id=str(row[0]))) is not None
            ]

    def save_agent_state(self, state: AgentDeliveryState) -> None:
        with self._lock:
            if self._connection is None:
                self._agent_states[(state.branch_id, state.agent_id)] = replace(state)
                return
            self._connection.execute(
                """
                insert into team_conversation_agent_state (
                    team_id,
                    conversation_id,
                    branch_id,
                    agent_id,
                    last_delivered_seq,
                    running,
                    queued,
                    queued_after_seq,
                    current_run_id,
                    current_snapshot_seq,
                    stop_requested,
                    last_identity_refresh_seq,
                    token_estimate_since_identity_refresh
                )
                values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                on conflict(team_id, conversation_id, branch_id, agent_id) do update set
                    last_delivered_seq = excluded.last_delivered_seq,
                    running = excluded.running,
                    queued = excluded.queued,
                    queued_after_seq = excluded.queued_after_seq,
                    current_run_id = excluded.current_run_id,
                    current_snapshot_seq = excluded.current_snapshot_seq,
                    stop_requested = excluded.stop_requested,
                    last_identity_refresh_seq = excluded.last_identity_refresh_seq,
                    token_estimate_since_identity_refresh = excluded.token_estimate_since_identity_refresh
                """,
                (
                    state.team_id,
                    state.conversation_id,
                    state.branch_id,
                    state.agent_id,
                    state.last_delivered_seq,
                    int(state.running),
                    int(state.queued),
                    state.queued_after_seq,
                    state.current_run_id,
                    state.current_snapshot_seq,
                    int(state.stop_requested),
                    state.last_identity_refresh_seq,
                    state.token_estimate_since_identity_refresh,
                ),
            )
            self._connection.commit()

    def enqueue(self, agent_id: str, after_seq: int, *, branch_id: str | None = None) -> AgentDeliveryState:
        with self._lock:
            state = self.ensure_agent_state(agent_id, branch_id=branch_id)
            queued_after_seq = max(after_seq, state.queued_after_seq or 0)
            updated = replace(state, queued=True, queued_after_seq=queued_after_seq)
            self.save_agent_state(updated)
            return updated

    def cancel_queued(self, agent_id: str, *, branch_id: str | None = None) -> AgentDeliveryState:
        with self._lock:
            state = self.ensure_agent_state(agent_id, branch_id=branch_id)
            if state.running:
                return state
            updated = replace(state, queued=False, queued_after_seq=None, stop_requested=False)
            self.save_agent_state(updated)
            return updated

    def clear_pending_queue(self, *, branch_id: str | None = None) -> list[AgentDeliveryState]:
        with self._lock:
            cleared = []
            for state in self.list_agent_states(branch_id=self._resolved_branch_id(branch_id)):
                if state.queued and not state.running:
                    cleared.append(self.cancel_queued(state.agent_id, branch_id=state.branch_id))
            return cleared

    def pending_idle_agent_ids(self, *, limit: int | None = None, branch_id: str | None = None) -> list[str]:
        states = [
            state
            for state in self.list_agent_states(branch_id=self._resolved_branch_id(branch_id))
            if state.queued and not state.running and not state.stop_requested
        ]
        states.sort(key=lambda item: (item.queued_after_seq or 0, item.agent_id))
        agent_ids = [state.agent_id for state in states]
        return agent_ids[:limit] if limit is not None else agent_ids

    def running_count(self, *, branch_id: str | None = None) -> int:
        return sum(1 for state in self.list_agent_states(branch_id=self._resolved_branch_id(branch_id)) if state.running)

    def mark_run_started(
        self,
        agent_id: str,
        *,
        run_id: str,
        snapshot_seq: int,
        branch_id: str | None = None,
        logical_thread_key: str | None = None,
        physical_thread_id: str | None = None,
    ) -> AgentDeliveryState:
        with self._lock:
            resolved_branch_id = self._resolved_branch_id(branch_id)
            state = self.ensure_agent_state(agent_id, branch_id=resolved_branch_id)
            keep_queued = bool(state.queued and state.queued_after_seq is not None and state.queued_after_seq > snapshot_seq)
            updated = replace(
                state,
                running=True,
                queued=keep_queued,
                queued_after_seq=state.queued_after_seq if keep_queued else None,
                current_run_id=run_id,
                current_snapshot_seq=snapshot_seq,
                stop_requested=False,
            )
            self.save_agent_state(updated)
            self._save_run(
                ConversationRun(
                    id=run_id,
                    team_id=self.team_id,
                    conversation_id=self.conversation_id,
                    branch_id=resolved_branch_id,
                    agent_id=agent_id,
                    logical_thread_key=logical_thread_key,
                    physical_thread_id=physical_thread_id,
                    status="running",
                    snapshot_seq=snapshot_seq,
                    started_at=self._now(),
                    commit_state="pending",
                )
            )
            return updated

    def complete_run(
        self,
        agent_id: str,
        *,
        run_id: str,
        snapshot_seq: int,
        delivered: bool,
        identity_inserted: bool,
        token_estimate: int,
        branch_id: str | None = None,
    ) -> bool:
        with self._lock:
            state = self.ensure_agent_state(agent_id, branch_id=branch_id)
            if state.current_run_id != run_id:
                return False
            queued_after_seq = state.queued_after_seq
            keep_queued = bool(state.queued and queued_after_seq is not None and queued_after_seq > snapshot_seq)
            updated = replace(
                state,
                last_delivered_seq=max(state.last_delivered_seq, snapshot_seq) if delivered else state.last_delivered_seq,
                running=False,
                queued=keep_queued,
                queued_after_seq=queued_after_seq if keep_queued else None,
                current_run_id=None,
                current_snapshot_seq=None,
                stop_requested=False,
                last_identity_refresh_seq=snapshot_seq if delivered and identity_inserted else state.last_identity_refresh_seq,
                token_estimate_since_identity_refresh=(
                    0
                    if delivered and identity_inserted
                    else state.token_estimate_since_identity_refresh + (token_estimate if delivered else 0)
                ),
            )
            self.save_agent_state(updated)
            return True

    def request_stop(self, agent_id: str, *, branch_id: str | None = None) -> AgentDeliveryState:
        with self._lock:
            state = self.ensure_agent_state(agent_id, branch_id=branch_id)
            updated = replace(state, stop_requested=True)
            self.save_agent_state(updated)
            return updated

    def is_stop_requested(self, agent_id: str, run_id: str, *, branch_id: str | None = None) -> bool:
        state = self.get_agent_state(agent_id, branch_id=branch_id)
        return bool(state and state.current_run_id == run_id and state.stop_requested)

    def record_delivery(
        self,
        *,
        agent_id: str,
        status: DeliveryStatus,
        run_id: str | None = None,
        snapshot_seq: int | None = None,
        error: str | None = None,
        branch_id: str | None = None,
    ) -> ConversationDelivery:
        delivery = ConversationDelivery(
            id=f"dlv_{uuid.uuid4().hex}",
            team_id=self.team_id,
            conversation_id=self.conversation_id,
            branch_id=self._resolved_branch_id(branch_id),
            agent_id=agent_id,
            run_id=run_id,
            snapshot_seq=snapshot_seq,
            status=status,
            created_at=self._now(),
            completed_at=self._now(),
            error=error,
        )
        with self._lock:
            if self._connection is None:
                self._deliveries.append(delivery)
                self._complete_run_record_from_delivery(delivery)
                return delivery
            self._connection.execute(
                """
                insert into team_conversation_deliveries (
                    team_id,
                    conversation_id,
                    branch_id,
                    id,
                    agent_id,
                    run_id,
                    snapshot_seq,
                    status,
                    created_at,
                    completed_at,
                    error
                )
                values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    delivery.team_id,
                    delivery.conversation_id,
                    delivery.branch_id,
                    delivery.id,
                    delivery.agent_id,
                    delivery.run_id,
                    delivery.snapshot_seq,
                    delivery.status,
                    delivery.created_at,
                    delivery.completed_at,
                    delivery.error,
                ),
            )
            self._complete_run_record_from_delivery(delivery)
            self._connection.commit()
            return delivery

    def record_model_attempt_started(
        self,
        *,
        attempt_id: str,
        run_id: str,
        agent_id: str,
        provider: str,
        model: str,
        attempt_number: int,
        max_attempts: int,
        timeout_mode: str,
        timeout_seconds: float,
        branch_id: str | None = None,
    ) -> ConversationModelAttempt:
        attempt = ConversationModelAttempt(
            id=attempt_id,
            team_id=self.team_id,
            conversation_id=self.conversation_id,
            branch_id=self._resolved_branch_id(branch_id),
            run_id=run_id,
            agent_id=agent_id,
            provider=provider,
            model=model,
            attempt_number=attempt_number,
            max_attempts=max_attempts,
            timeout_mode=timeout_mode,
            timeout_seconds=timeout_seconds,
            started_at=self._now(),
        )
        with self._lock:
            if self._connection is None:
                self._model_attempts[attempt.id] = attempt
                return attempt
            self._connection.execute(
                """
                insert or replace into team_conversation_model_attempts (
                    team_id,
                    conversation_id,
                    branch_id,
                    id,
                    run_id,
                    agent_id,
                    provider,
                    model,
                    attempt_number,
                    max_attempts,
                    timeout_mode,
                    timeout_seconds,
                    started_at,
                    completed_at,
                    status,
                    normalized_failure_code,
                    provider_error_type
                )
                values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    attempt.team_id,
                    attempt.conversation_id,
                    attempt.branch_id,
                    attempt.id,
                    attempt.run_id,
                    attempt.agent_id,
                    attempt.provider,
                    attempt.model,
                    attempt.attempt_number,
                    attempt.max_attempts,
                    attempt.timeout_mode,
                    attempt.timeout_seconds,
                    attempt.started_at,
                    attempt.completed_at,
                    attempt.status,
                    attempt.normalized_failure_code,
                    attempt.provider_error_type,
                ),
            )
            self._connection.commit()
            return attempt

    def record_model_attempt_finished(
        self,
        attempt_id: str,
        *,
        status: ModelAttemptStatus,
        normalized_failure_code: str | None = None,
        provider_error_type: str | None = None,
    ) -> ConversationModelAttempt | None:
        if status not in _MODEL_ATTEMPT_STATUSES:
            return None
        with self._lock:
            attempt = self.get_model_attempt(attempt_id)
            if attempt is None:
                return None
            updated = replace(
                attempt,
                completed_at=self._now(),
                status=status,
                normalized_failure_code=normalized_failure_code,
                provider_error_type=provider_error_type,
            )
            if self._connection is None:
                self._model_attempts[attempt_id] = updated
                return updated
            self._connection.execute(
                """
                update team_conversation_model_attempts
                set completed_at = ?,
                    status = ?,
                    normalized_failure_code = ?,
                    provider_error_type = ?
                where team_id = ? and conversation_id = ? and id = ?
                """,
                (
                    updated.completed_at,
                    updated.status,
                    updated.normalized_failure_code,
                    updated.provider_error_type,
                    self.team_id,
                    self.conversation_id,
                    attempt_id,
                ),
            )
            self._connection.commit()
            return updated

    def get_model_attempt(self, attempt_id: str) -> ConversationModelAttempt | None:
        with self._lock:
            if self._connection is None:
                attempt = self._model_attempts.get(attempt_id)
                return replace(attempt) if attempt is not None else None
            row = self._connection.execute(
                """
                select
                    branch_id,
                    id,
                    run_id,
                    agent_id,
                    provider,
                    model,
                    attempt_number,
                    max_attempts,
                    timeout_mode,
                    timeout_seconds,
                    started_at,
                    completed_at,
                    status,
                    normalized_failure_code,
                    provider_error_type
                from team_conversation_model_attempts
                where team_id = ? and conversation_id = ? and id = ?
                """,
                (self.team_id, self.conversation_id, attempt_id),
            ).fetchone()
            return self._model_attempt_from_row(row) if row is not None else None

    def list_model_attempts(self, *, run_id: str | None = None) -> list[ConversationModelAttempt]:
        with self._lock:
            if self._connection is None:
                attempts = [
                    attempt
                    for attempt in self._model_attempts.values()
                    if run_id is None or attempt.run_id == run_id
                ]
                return [replace(attempt) for attempt in sorted(attempts, key=lambda item: (item.started_at, item.id))]
            clauses = ["team_id = ?", "conversation_id = ?"]
            params: list[object] = [self.team_id, self.conversation_id]
            if run_id is not None:
                clauses.append("run_id = ?")
                params.append(run_id)
            rows = self._connection.execute(
                f"""
                select
                    branch_id,
                    id,
                    run_id,
                    agent_id,
                    provider,
                    model,
                    attempt_number,
                    max_attempts,
                    timeout_mode,
                    timeout_seconds,
                    started_at,
                    completed_at,
                    status,
                    normalized_failure_code,
                    provider_error_type
                from team_conversation_model_attempts
                where {" and ".join(clauses)}
                order by started_at asc, id asc
                """,
                tuple(params),
            ).fetchall()
            return [self._model_attempt_from_row(row) for row in rows]

    def get_run(self, run_id: str) -> ConversationRun | None:
        with self._lock:
            if self._connection is None:
                run = self._runs.get(run_id)
                return replace(run) if run is not None else None
            row = self._connection.execute(
                """
                select
                    id,
                    branch_id,
                    agent_id,
                    logical_thread_key,
                    physical_thread_id,
                    status,
                    stop_kind,
                    snapshot_seq,
                    started_at,
                    completed_at,
                    stable_checkpoint_id,
                    latest_checkpoint_id,
                    checkpoint_stability,
                    usable_for_fork,
                    usable_for_continue,
                    commit_state
                from team_conversation_runs
                where team_id = ? and conversation_id = ? and id = ?
                """,
                (self.team_id, self.conversation_id, run_id),
            ).fetchone()
            return self._run_from_row(row) if row is not None else None

    def list_runs(self, *, branch_id: str | None | _UnsetType = _UNSET) -> list[ConversationRun]:
        with self._lock:
            resolved_branch_id = self.current_branch_id() if branch_id is _UNSET else branch_id
            if self._connection is None:
                runs = [
                    run
                    for run in self._runs.values()
                    if resolved_branch_id is None or run.branch_id == resolved_branch_id
                ]
                return [replace(run) for run in sorted(runs, key=lambda item: (item.started_at, item.id))]
            clauses = ["team_id = ?", "conversation_id = ?"]
            params: list[object] = [self.team_id, self.conversation_id]
            if resolved_branch_id is not None:
                clauses.append("branch_id = ?")
                params.append(resolved_branch_id)
            rows = self._connection.execute(
                f"""
                select
                    id,
                    branch_id,
                    agent_id,
                    logical_thread_key,
                    physical_thread_id,
                    status,
                    stop_kind,
                    snapshot_seq,
                    started_at,
                    completed_at,
                    stable_checkpoint_id,
                    latest_checkpoint_id,
                    checkpoint_stability,
                    usable_for_fork,
                    usable_for_continue,
                    commit_state
                from team_conversation_runs
                where {" and ".join(clauses)}
                order by started_at asc, id asc
                """,
                tuple(params),
            ).fetchall()
            return [self._run_from_row(row) for row in rows]

    def ensure_branch_thread(
        self,
        *,
        branch_id: str | None,
        logical_thread_key: str,
        physical_thread_id: str,
        created_by_commit_id: str | None = None,
    ) -> ConversationBranchThread:
        with self._lock:
            resolved_branch_id = self._resolved_branch_id(branch_id)
            existing = self.get_branch_thread(branch_id=resolved_branch_id, logical_thread_key=logical_thread_key)
            if existing is not None:
                return existing
            forked_from_branch_id, forked_from_thread_id, forked_from_checkpoint_id = self._fork_branch_thread_if_possible(
                branch_id=resolved_branch_id,
                logical_thread_key=logical_thread_key,
                target_physical_thread_id=physical_thread_id,
            )
            branch_thread = ConversationBranchThread(
                team_id=self.team_id,
                conversation_id=self.conversation_id,
                branch_id=resolved_branch_id,
                logical_thread_key=logical_thread_key,
                physical_thread_id=physical_thread_id,
                forked_from_branch_id=forked_from_branch_id,
                forked_from_thread_id=forked_from_thread_id,
                forked_from_checkpoint_id=forked_from_checkpoint_id,
                created_by_commit_id=created_by_commit_id,
            )
            self._save_branch_thread(branch_thread)
            return branch_thread

    def get_branch_thread(self, *, branch_id: str, logical_thread_key: str) -> ConversationBranchThread | None:
        with self._lock:
            if self._connection is None:
                thread = self._branch_threads.get((branch_id, logical_thread_key))
                if thread is None or thread.status != "active":
                    return None
                return replace(thread)
            row = self._connection.execute(
                """
                select
                    branch_id,
                    logical_thread_key,
                    physical_thread_id,
                    forked_from_branch_id,
                    forked_from_thread_id,
                    forked_from_checkpoint_id,
                    created_by_commit_id,
                    status
                from team_conversation_branch_threads
                where team_id = ? and conversation_id = ? and branch_id = ? and logical_thread_key = ?
                """,
                (self.team_id, self.conversation_id, branch_id, logical_thread_key),
            ).fetchone()
            if row is None:
                return None
            thread = self._branch_thread_from_row(row)
            return thread if thread.status == "active" else None

    def list_branch_threads(self, *, branch_id: str | None | _UnsetType = _UNSET) -> list[ConversationBranchThread]:
        with self._lock:
            resolved_branch_id = self.current_branch_id() if branch_id is _UNSET else branch_id
            if self._connection is None:
                threads = [
                    thread
                    for (thread_branch_id, _logical_key), thread in self._branch_threads.items()
                    if resolved_branch_id is None or thread_branch_id == resolved_branch_id
                ]
                return [replace(thread) for thread in sorted(threads, key=lambda item: (item.branch_id, item.logical_thread_key))]
            clauses = ["team_id = ?", "conversation_id = ?"]
            params: list[object] = [self.team_id, self.conversation_id]
            if resolved_branch_id is not None:
                clauses.append("branch_id = ?")
                params.append(resolved_branch_id)
            rows = self._connection.execute(
                f"""
                select
                    branch_id,
                    logical_thread_key,
                    physical_thread_id,
                    forked_from_branch_id,
                    forked_from_thread_id,
                    forked_from_checkpoint_id,
                    created_by_commit_id,
                    status
                from team_conversation_branch_threads
                where {" and ".join(clauses)}
                order by branch_id asc, logical_thread_key asc
                """,
                tuple(params),
            ).fetchall()
            return [self._branch_thread_from_row(row) for row in rows]

    def record_thread_frontier(
        self,
        *,
        frontier_id: str,
        branch_id: str,
        event_id: str,
        event_boundary: ThreadFrontierBoundary,
        logical_thread_key: str,
        physical_thread_id: str,
        checkpoint_id: str | None,
        run_id: str | None = None,
        parent_logical_thread_key: str | None = None,
        usable_for_fork: bool = False,
        usable_for_continue: bool = False,
    ) -> ThreadFrontier:
        frontier = ThreadFrontier(
            frontier_id=frontier_id,
            team_id=self.team_id,
            conversation_id=self.conversation_id,
            branch_id=branch_id,
            event_id=event_id,
            event_boundary=event_boundary,
            logical_thread_key=logical_thread_key,
            physical_thread_id=physical_thread_id,
            checkpoint_id=checkpoint_id,
            run_id=run_id,
            parent_logical_thread_key=parent_logical_thread_key,
            usable_for_fork=usable_for_fork,
            usable_for_continue=usable_for_continue,
            created_at=self._now(),
        )
        with self._lock:
            if self._connection is None:
                self._thread_frontiers.append(frontier)
                return frontier
            self._connection.execute(
                """
                insert into team_conversation_thread_frontiers (
                    team_id,
                    conversation_id,
                    frontier_id,
                    branch_id,
                    event_id,
                    event_boundary,
                    logical_thread_key,
                    physical_thread_id,
                    checkpoint_id,
                    run_id,
                    parent_logical_thread_key,
                    usable_for_fork,
                    usable_for_continue,
                    created_at
                )
                values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                on conflict(team_id, conversation_id, frontier_id, event_boundary, logical_thread_key) do update set
                    branch_id = excluded.branch_id,
                    event_id = excluded.event_id,
                    physical_thread_id = excluded.physical_thread_id,
                    checkpoint_id = excluded.checkpoint_id,
                    run_id = excluded.run_id,
                    parent_logical_thread_key = excluded.parent_logical_thread_key,
                    usable_for_fork = excluded.usable_for_fork,
                    usable_for_continue = excluded.usable_for_continue,
                    created_at = excluded.created_at
                """,
                (
                    frontier.team_id,
                    frontier.conversation_id,
                    frontier.frontier_id,
                    frontier.branch_id,
                    frontier.event_id,
                    frontier.event_boundary,
                    frontier.logical_thread_key,
                    frontier.physical_thread_id,
                    frontier.checkpoint_id,
                    frontier.run_id,
                    frontier.parent_logical_thread_key,
                    int(frontier.usable_for_fork),
                    int(frontier.usable_for_continue),
                    frontier.created_at,
                ),
            )
            self._connection.commit()
            return frontier

    def get_thread_frontier(
        self,
        *,
        frontier_id: str,
        branch_id: str,
        logical_thread_key: str,
        event_boundary: ThreadFrontierBoundary = "after",
    ) -> ThreadFrontier | None:
        with self._lock:
            if self._connection is None:
                for frontier in reversed(self._thread_frontiers):
                    if (
                        frontier.frontier_id == frontier_id
                        and frontier.branch_id == branch_id
                        and frontier.logical_thread_key == logical_thread_key
                        and frontier.event_boundary == event_boundary
                    ):
                        return replace(frontier)
                return None
            row = self._connection.execute(
                """
                select
                    frontier_id,
                    branch_id,
                    event_id,
                    event_boundary,
                    logical_thread_key,
                    physical_thread_id,
                    checkpoint_id,
                    run_id,
                    parent_logical_thread_key,
                    usable_for_fork,
                    usable_for_continue,
                    created_at
                from team_conversation_thread_frontiers
                where team_id = ?
                  and conversation_id = ?
                  and frontier_id = ?
                  and branch_id = ?
                  and logical_thread_key = ?
                  and event_boundary = ?
                """,
                (self.team_id, self.conversation_id, frontier_id, branch_id, logical_thread_key, event_boundary),
            ).fetchone()
            return self._thread_frontier_from_row(row) if row is not None else None

    def list_thread_frontiers(self, *, branch_id: str | None | _UnsetType = _UNSET) -> list[ThreadFrontier]:
        with self._lock:
            resolved_branch_id = self.current_branch_id() if branch_id is _UNSET else branch_id
            if self._connection is None:
                frontiers = [
                    frontier
                    for frontier in self._thread_frontiers
                    if resolved_branch_id is None or frontier.branch_id == resolved_branch_id
                ]
                return [replace(frontier) for frontier in sorted(frontiers, key=lambda item: (item.created_at, item.frontier_id))]
            clauses = ["team_id = ?", "conversation_id = ?"]
            params: list[object] = [self.team_id, self.conversation_id]
            if resolved_branch_id is not None:
                clauses.append("branch_id = ?")
                params.append(resolved_branch_id)
            rows = self._connection.execute(
                f"""
                select
                    frontier_id,
                    branch_id,
                    event_id,
                    event_boundary,
                    logical_thread_key,
                    physical_thread_id,
                    checkpoint_id,
                    run_id,
                    parent_logical_thread_key,
                    usable_for_fork,
                    usable_for_continue,
                    created_at
                from team_conversation_thread_frontiers
                where {" and ".join(clauses)}
                order by created_at asc, frontier_id asc, logical_thread_key asc
                """,
                tuple(params),
            ).fetchall()
            return [self._thread_frontier_from_row(row) for row in rows]

    def create_control_event(
        self,
        *,
        branch_id: str | None,
        logical_thread_key: str,
        physical_thread_id: str,
        kind: str,
        content: str = "",
        parent_run_id: str | None = None,
    ) -> ConversationControlEvent:
        event = ConversationControlEvent(
            id=f"ctrl_{uuid.uuid4().hex}",
            team_id=self.team_id,
            conversation_id=self.conversation_id,
            branch_id=self._resolved_branch_id(branch_id),
            logical_thread_key=logical_thread_key,
            physical_thread_id=physical_thread_id,
            parent_run_id=parent_run_id,
            kind=kind,
            content=content,
            created_at=self._now(),
        )
        with self._lock:
            if self._connection is None:
                self._control_events.append(event)
                return event
            self._connection.execute(
                """
                insert into team_conversation_control_events (
                    team_id,
                    conversation_id,
                    id,
                    branch_id,
                    logical_thread_key,
                    physical_thread_id,
                    parent_run_id,
                    kind,
                    content,
                    created_at
                )
                values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    event.team_id,
                    event.conversation_id,
                    event.id,
                    event.branch_id,
                    event.logical_thread_key,
                    event.physical_thread_id,
                    event.parent_run_id,
                    event.kind,
                    event.content,
                    event.created_at,
                ),
            )
            self._connection.commit()
            return event

    def list_control_events(self, *, branch_id: str | None | _UnsetType = _UNSET) -> list[ConversationControlEvent]:
        with self._lock:
            resolved_branch_id = self.current_branch_id() if branch_id is _UNSET else branch_id
            if self._connection is None:
                events = [
                    event
                    for event in self._control_events
                    if resolved_branch_id is None or event.branch_id == resolved_branch_id
                ]
                return [replace(event) for event in sorted(events, key=lambda item: (item.created_at, item.id))]
            clauses = ["team_id = ?", "conversation_id = ?"]
            params: list[object] = [self.team_id, self.conversation_id]
            if resolved_branch_id is not None:
                clauses.append("branch_id = ?")
                params.append(resolved_branch_id)
            rows = self._connection.execute(
                f"""
                select
                    id,
                    branch_id,
                    logical_thread_key,
                    physical_thread_id,
                    parent_run_id,
                    kind,
                    content,
                    created_at
                from team_conversation_control_events
                where {" and ".join(clauses)}
                order by created_at asc, id asc
                """,
                tuple(params),
            ).fetchall()
            return [self._control_event_from_row(row) for row in rows]

    def record_external_side_effect(
        self,
        *,
        branch_id: str | None = None,
        kind: str,
        target: str,
        audit_payload: JsonMapping | None = None,
        run_id: str | None = None,
        agent_id: str | None = None,
        tool_call_id: str | None = None,
        not_rewindable: bool = True,
    ) -> ExternalSideEffect:
        payload = dict(audit_payload or {})
        if not is_json_object(payload):
            raise ValueError("external side effect audit_payload must be JSON-serializable.")
        side_effect = ExternalSideEffect(
            id=f"sidefx_{uuid.uuid4().hex}",
            team_id=self.team_id,
            conversation_id=self.conversation_id,
            branch_id=self._resolved_branch_id(branch_id),
            run_id=run_id,
            agent_id=agent_id,
            tool_call_id=tool_call_id,
            kind=kind,
            target=target,
            audit_payload=payload,
            not_rewindable=not_rewindable,
            created_at=self._now(),
        )
        with self._lock:
            if self._connection is None:
                self._external_side_effects.append(side_effect)
                return side_effect
            self._connection.execute(
                """
                insert into team_conversation_external_side_effects (
                    team_id,
                    conversation_id,
                    id,
                    branch_id,
                    run_id,
                    agent_id,
                    tool_call_id,
                    kind,
                    target,
                    audit_payload_json,
                    not_rewindable,
                    created_at
                )
                values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    side_effect.team_id,
                    side_effect.conversation_id,
                    side_effect.id,
                    side_effect.branch_id,
                    side_effect.run_id,
                    side_effect.agent_id,
                    side_effect.tool_call_id,
                    side_effect.kind,
                    side_effect.target,
                    json.dumps(side_effect.audit_payload, ensure_ascii=False),
                    int(side_effect.not_rewindable),
                    side_effect.created_at,
                ),
            )
            self._connection.commit()
            return side_effect

    def list_external_side_effects(self, *, branch_id: str | None | _UnsetType = _UNSET) -> list[ExternalSideEffect]:
        with self._lock:
            resolved_branch_id = self.current_branch_id() if branch_id is _UNSET else branch_id
            if self._connection is None:
                side_effects = [
                    side_effect
                    for side_effect in self._external_side_effects
                    if resolved_branch_id is None or side_effect.branch_id == resolved_branch_id
                ]
                return [replace(side_effect) for side_effect in sorted(side_effects, key=lambda item: (item.created_at, item.id))]
            clauses = ["team_id = ?", "conversation_id = ?"]
            params: list[object] = [self.team_id, self.conversation_id]
            if resolved_branch_id is not None:
                clauses.append("branch_id = ?")
                params.append(resolved_branch_id)
            rows = self._connection.execute(
                f"""
                select
                    id,
                    branch_id,
                    run_id,
                    agent_id,
                    tool_call_id,
                    kind,
                    target,
                    audit_payload_json,
                    not_rewindable,
                    created_at
                from team_conversation_external_side_effects
                where {" and ".join(clauses)}
                order by created_at asc, id asc
                """,
                tuple(params),
            ).fetchall()
            return [self._external_side_effect_from_row(row) for row in rows]

    def get_studio_branch_ui_state(
        self,
        *,
        participant_id: str = "human",
        branch_id: str | None = None,
    ) -> StudioBranchUiState:
        participant = self._non_empty_participant_id(participant_id)
        resolved_branch_id = self._resolved_branch_id(branch_id)
        with self._lock:
            if self._connection is None:
                state = self._studio_branch_ui_states.get((resolved_branch_id, participant))
                return replace(state) if state is not None else self._default_studio_branch_ui_state(resolved_branch_id, participant)
            row = self._connection.execute(
                """
                select
                    branch_id,
                    participant_id,
                    draft_content,
                    outbox_state_json,
                    editing_event_id,
                    selected_agent_id,
                    scroll_anchor_event_id,
                    updated_at
                from team_conversation_studio_branch_ui_state
                where team_id = ? and conversation_id = ? and branch_id = ? and participant_id = ?
                """,
                (self.team_id, self.conversation_id, resolved_branch_id, participant),
            ).fetchone()
            return (
                self._studio_branch_ui_state_from_row(row)
                if row is not None
                else self._default_studio_branch_ui_state(resolved_branch_id, participant)
            )

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
    ) -> StudioBranchUiState:
        participant = self._non_empty_participant_id(participant_id)
        resolved_branch_id = self._resolved_branch_id(branch_id)
        resolved_outbox_state: JsonValue = [] if outbox_state is None else outbox_state
        if not is_json_value(resolved_outbox_state):
            raise ValueError("studio branch UI outbox_state must be JSON-serializable.")
        state = StudioBranchUiState(
            team_id=self.team_id,
            conversation_id=self.conversation_id,
            branch_id=resolved_branch_id,
            participant_id=participant,
            draft_content=draft_content,
            outbox_state=resolved_outbox_state,
            editing_event_id=editing_event_id,
            selected_agent_id=selected_agent_id,
            scroll_anchor_event_id=scroll_anchor_event_id,
            updated_at=self._now(),
        )
        with self._lock:
            if self._connection is None:
                self._studio_branch_ui_states[(resolved_branch_id, participant)] = state
                return replace(state)
            self._connection.execute(
                """
                insert into team_conversation_studio_branch_ui_state (
                    team_id,
                    conversation_id,
                    branch_id,
                    participant_id,
                    draft_content,
                    outbox_state_json,
                    editing_event_id,
                    selected_agent_id,
                    scroll_anchor_event_id,
                    updated_at
                )
                values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                on conflict(team_id, conversation_id, branch_id, participant_id) do update set
                    draft_content = excluded.draft_content,
                    outbox_state_json = excluded.outbox_state_json,
                    editing_event_id = excluded.editing_event_id,
                    selected_agent_id = excluded.selected_agent_id,
                    scroll_anchor_event_id = excluded.scroll_anchor_event_id,
                    updated_at = excluded.updated_at
                """,
                (
                    state.team_id,
                    state.conversation_id,
                    state.branch_id,
                    state.participant_id,
                    state.draft_content,
                    json.dumps(state.outbox_state, ensure_ascii=False),
                    state.editing_event_id,
                    state.selected_agent_id,
                    state.scroll_anchor_event_id,
                    state.updated_at,
                ),
            )
            self._connection.commit()
            return state

    def latest_checkpoint_id(self, physical_thread_id: str, *, checkpoint_ns: str = "") -> str | None:
        if self._connection is None or not self._table_exists("checkpoints"):
            return None
        row = self._connection.execute(
            """
            select checkpoint_id
            from checkpoints
            where thread_id = ? and checkpoint_ns = ?
            order by checkpoint_id desc
            limit 1
            """,
            (physical_thread_id, checkpoint_ns),
        ).fetchone()
        return str(row[0]) if row is not None else None

    def latest_usable_run_checkpoint_id(
        self,
        *,
        branch_id: str,
        logical_thread_key: str,
        for_continue: bool,
    ) -> str | None:
        runs = [
            run
            for run in self.list_runs(branch_id=branch_id)
            if run.logical_thread_key == logical_thread_key
            and run.commit_state == "committed"
            and (run.usable_for_continue if for_continue else run.usable_for_fork)
            and run.stable_checkpoint_id is not None
        ]
        if not runs:
            return None
        runs.sort(key=lambda item: (item.completed_at or item.started_at, item.id))
        return runs[-1].stable_checkpoint_id

    def list_tool_call_edges(
        self,
        *,
        branch_id: str,
        run_id: str,
        status: str | None = None,
    ) -> list[ToolCallEdge]:
        if self._connection is None or not self._table_exists("tool_call_edges"):
            return []
        clauses = ["team_id = ?", "conversation_id = ?", "branch_id = ?", "run_id = ?"]
        params: list[object] = [self.team_id, self.conversation_id, branch_id, run_id]
        if status is not None:
            clauses.append("status = ?")
            params.append(status)
        rows = self._connection.execute(
            f"""
            select
                team_id,
                conversation_id,
                id,
                commit_id,
                branch_id,
                parent_logical_thread_key,
                parent_physical_thread_id,
                relation_id,
                target_agent_id,
                child_logical_thread_key,
                child_physical_thread_id,
                run_id,
                status
            from tool_call_edges
            where {" and ".join(clauses)}
            order by id asc
            """,
            tuple(params),
        ).fetchall()
        edges = []
        for row in rows:
            status_value = str(row[12])
            status = cast(ToolCallEdgeStatus, status_value) if status_value in {"running", "success", "failed"} else "failed"
            edges.append(
                ToolCallEdge(
                    id=str(row[2]),
                    team_id=str(row[0]),
                    conversation_id=str(row[1]),
                    commit_id=str(row[3]),
                    branch_id=str(row[4]),
                    parent_logical_thread_key=str(row[5]),
                    parent_physical_thread_id=str(row[6]),
                    relation_id=str(row[7]),
                    target_agent_id=str(row[8]),
                    child_logical_thread_key=str(row[9]),
                    child_physical_thread_id=str(row[10]),
                    run_id=str(row[11]) if row[11] is not None else None,
                    status=status,
                )
            )
        return edges

    def reconcile_incomplete_commits(self) -> dict[str, int]:
        with self._lock:
            finalized_runs = 0
            orphaned_runs = 0
            orphaned_branch_threads = 0
            failed_tool_call_edges = 0
            pending_runs = [run for run in self.list_runs(branch_id=None) if run.commit_state == "pending"]
            for run in pending_runs:
                delivery = self._latest_delivery_for_run(run.id)
                if delivery is not None:
                    self._complete_run_record_from_delivery(delivery)
                    finalized_runs += 1
                    continue
                self._orphan_run(run)
                self._fail_running_model_attempts_for_run(run.id)
                self.record_delivery(
                    agent_id=run.agent_id,
                    run_id=run.id,
                    snapshot_seq=run.snapshot_seq,
                    status="failed",
                    error=ORPHANED_RUN_DELIVERY_ERROR,
                    branch_id=run.branch_id,
                )
                orphaned_runs += 1

            committed_run_ids = {
                run.id
                for run in self.list_runs(branch_id=None)
                if run.commit_state == "committed"
            }
            committed_causal_commit_ids = self._committed_causal_commit_ids(committed_run_ids)
            for branch_thread in self.list_branch_threads(branch_id=None):
                commit_id = branch_thread.created_by_commit_id
                if branch_thread.status != "active" or commit_id is None or commit_id in committed_causal_commit_ids:
                    continue
                self._save_branch_thread(replace(branch_thread, status="orphaned"))
                orphaned_branch_threads += 1

            if self._connection is not None and self._table_exists("tool_call_edges"):
                orphaned_run_ids = [run.id for run in self.list_runs(branch_id=None) if run.commit_state == "orphaned"]
                for run_id in orphaned_run_ids:
                    cursor = self._connection.execute(
                        """
                        update tool_call_edges
                        set status = 'failed'
                        where team_id = ? and conversation_id = ? and run_id = ? and status = 'running'
                        """,
                        (self.team_id, self.conversation_id, run_id),
                    )
                    failed_tool_call_edges += cursor.rowcount if cursor.rowcount is not None else 0
                self._connection.commit()

            return {
                "finalized_runs": finalized_runs,
                "orphaned_runs": orphaned_runs,
                "orphaned_branch_threads": orphaned_branch_threads,
                "failed_tool_call_edges": failed_tool_call_edges,
            }

    def _committed_causal_commit_ids(self, committed_run_ids: set[str]) -> set[str]:
        committed_commit_ids = set(committed_run_ids)
        if self._connection is None or not self._table_exists("tool_call_edges"):
            return committed_commit_ids
        rows = self._connection.execute(
            """
            select commit_id, run_id
            from tool_call_edges
            where team_id = ? and conversation_id = ? and status = 'success'
            """,
            (self.team_id, self.conversation_id),
        ).fetchall()
        for commit_id, run_id in rows:
            if run_id is None or str(run_id) in committed_run_ids:
                committed_commit_ids.add(str(commit_id))
        return committed_commit_ids

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
        branch = ConversationBranch(
            id=f"branch_{uuid.uuid4().hex}",
            team_id=self.team_id,
            conversation_id=self.conversation_id,
            label=label or f"Branch {len(self.list_branches(include_archived=True)) + 1}",
            parent_branch_id=parent_branch_id or self.current_branch_id(),
            origin_checkpoint_id=origin_checkpoint_id,
            origin_event_id=origin_event_id,
            origin_logical_message_id=origin_logical_message_id,
            origin_previous_event_id=origin_previous_event_id,
            origin_event_seq=origin_event_seq,
            created_at=self._now(),
            current=False,
            status="persisted",
            head_checkpoint_id=head_checkpoint_id,
            archived_at=None,
        )
        with self._lock:
            if self._connection is None:
                self._branches[branch.id] = replace(branch)
                self._initialize_branch_agent_states(branch)
                return replace(branch)
            self._connection.execute(
                """
                insert into team_conversation_branches (
                    team_id,
                    conversation_id,
                    id,
                    label,
                    parent_branch_id,
                    origin_checkpoint_id,
                    origin_event_id,
                    origin_logical_message_id,
                    origin_previous_event_id,
                    origin_event_seq,
                    created_at,
                    current,
                    head_checkpoint_id,
                    archived_at
                )
                values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    branch.team_id,
                    branch.conversation_id,
                    branch.id,
                    branch.label,
                    branch.parent_branch_id,
                    branch.origin_checkpoint_id,
                    branch.origin_event_id,
                    branch.origin_logical_message_id,
                    branch.origin_previous_event_id,
                    branch.origin_event_seq,
                    branch.created_at,
                    int(branch.current),
                    branch.head_checkpoint_id,
                    branch.archived_at,
                ),
            )
            self._connection.commit()
            self._initialize_branch_agent_states(branch)
            return replace(branch)

    def list_branches(self, *, include_archived: bool = False) -> list[ConversationBranch]:
        with self._lock:
            if self._connection is None:
                return [
                    replace(self._branches[branch_id])
                    for branch_id in sorted(self._branches)
                    if include_archived or self._branches[branch_id].archived_at is None
                ]
            clauses = ["team_id = ?", "conversation_id = ?"]
            params: list[object] = [self.team_id, self.conversation_id]
            if not include_archived:
                clauses.append("archived_at is null")
            rows = self._connection.execute(
                f"""
                select
                    id,
                    label,
                    parent_branch_id,
                    origin_checkpoint_id,
                    origin_event_id,
                    origin_logical_message_id,
                    origin_previous_event_id,
                    origin_event_seq,
                    created_at,
                    current,
                    head_checkpoint_id,
                    archived_at
                from team_conversation_branches
                where {" and ".join(clauses)}
                order by created_at asc, id asc
                """,
                tuple(params),
            ).fetchall()
            return [self._branch_from_row(row) for row in rows]

    def archive_branch(self, branch_id: str) -> ConversationBranch | None:
        with self._lock:
            if branch_id == "branch_main":
                raise ValueError("branch_main cannot be archived.")
            branch = self._branch_by_id(branch_id)
            if branch is None:
                return None
            if branch.current or branch_id == self.current_branch_id():
                raise ValueError("cannot archive the current branch.")
            if branch.archived_at is not None:
                return replace(branch)
            archived = replace(branch, current=False, archived_at=self._now())
            if self._connection is None:
                self._branches[branch_id] = replace(archived)
                return replace(archived)
            self._connection.execute(
                """
                update team_conversation_branches
                set archived_at = ?, current = 0
                where team_id = ? and conversation_id = ? and id = ?
                """,
                (archived.archived_at, self.team_id, self.conversation_id, branch_id),
            )
            self._connection.commit()
            return replace(archived)

    def current_branch_id(self) -> str:
        with self._lock:
            if self._connection is None:
                return self._current_branch_id
            row = self._connection.execute(
                """
                select id
                from team_conversation_branches
                where team_id = ? and conversation_id = ? and current = 1 and archived_at is null
                order by created_at desc, id desc
                limit 1
                """,
                (self.team_id, self.conversation_id),
            ).fetchone()
            return str(row[0]) if row is not None else "branch_main"

    def switch_branch(self, branch_id: str) -> ConversationBranch | None:
        with self._lock:
            if branch_id == "branch_main":
                self._set_current_branch(None)
                return None
            if self._connection is None:
                branch = self._branch_by_id(branch_id)
                if branch is None or branch.archived_at is not None:
                    return None
                self._set_current_branch(branch_id)
                return replace(self._branches[branch_id])
            branch = self._branch_by_id(branch_id)
            if branch is None or branch.archived_at is not None:
                return None
            self._set_current_branch(branch_id)
            return self._branch_by_id(branch_id)

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
        if kind not in _INTERRUPT_KINDS:
            raise ValueError("interrupt kind is not supported.")
        payload_dict = dict(payload or {})
        if not is_json_object(payload_dict):
            raise ValueError("interrupt payload must be JSON-serializable.")
        resolved_branch_id = self._resolved_branch_id(branch_id)
        interrupt = ConversationInterrupt(
            id=interrupt_id or f"interrupt_{uuid.uuid4().hex}",
            team_id=self.team_id,
            conversation_id=self.conversation_id,
            branch_id=resolved_branch_id,
            run_id=run_id,
            agent_id=agent_id,
            checkpoint_id=checkpoint_id,
            created_at=self._now(),
            kind=kind,
            payload=payload_dict,
        )
        with self._lock:
            if self._connection is None:
                self._interrupts[interrupt.id] = replace(interrupt)
                return replace(interrupt)
            self._connection.execute(
                """
                insert into team_conversation_interrupts (
                    team_id,
                    conversation_id,
                    id,
                    branch_id,
                    run_id,
                    agent_id,
                    checkpoint_id,
                    created_at,
                    kind,
                    payload_json,
                    status,
                    decisions_json
                )
                values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    interrupt.team_id,
                    interrupt.conversation_id,
                    interrupt.id,
                    interrupt.branch_id,
                    interrupt.run_id,
                    interrupt.agent_id,
                    interrupt.checkpoint_id,
                    interrupt.created_at,
                    interrupt.kind,
                    json.dumps(interrupt.payload, ensure_ascii=False),
                    interrupt.status,
                    json.dumps([], ensure_ascii=False),
                ),
            )
            self._connection.commit()
            return replace(interrupt)

    def list_interrupts(
        self,
        *,
        active_only: bool = True,
        branch_id: str | None | _UnsetType = _UNSET,
    ) -> list[ConversationInterrupt]:
        with self._lock:
            resolved_branch_id = self.current_branch_id() if branch_id is _UNSET else branch_id
            if self._connection is None:
                interrupts = list(self._interrupts.values())
                if resolved_branch_id is not None:
                    interrupts = [interrupt for interrupt in interrupts if interrupt.branch_id == resolved_branch_id]
                if active_only:
                    interrupts = [interrupt for interrupt in interrupts if interrupt.status == "pending"]
                return [replace(interrupt) for interrupt in sorted(interrupts, key=lambda item: (item.created_at, item.id))]
            clauses = ["team_id = ?", "conversation_id = ?"]
            params: list[object] = [self.team_id, self.conversation_id]
            if resolved_branch_id is not None:
                clauses.append("branch_id = ?")
                params.append(resolved_branch_id)
            if active_only:
                clauses.append("status = ?")
                params.append("pending")
            rows = self._connection.execute(
                f"""
                select
                    id,
                    branch_id,
                    run_id,
                    agent_id,
                    checkpoint_id,
                    created_at,
                    kind,
                    payload_json,
                    status,
                    decisions_json
                from team_conversation_interrupts
                where {" and ".join(clauses)}
                order by created_at asc, id asc
                """,
                tuple(params),
            ).fetchall()
            return [self._interrupt_from_row(row) for row in rows]

    def resume_interrupt(
        self,
        interrupt_id: str,
        *,
        decision: ConversationInterruptDecision,
        response: str | None = None,
        edited_payload: JsonMapping | None = None,
        branch_id: str | None | _UnsetType = _UNSET,
    ) -> ConversationInterrupt | None:
        if decision not in _INTERRUPT_DECISIONS:
            raise ValueError("interrupt decision is not supported.")
        edited_payload_dict = dict(edited_payload or {})
        if not is_json_object(edited_payload_dict):
            raise ValueError("interrupt edited_payload must be JSON-serializable.")
        with self._lock:
            resolved_branch_id = self.current_branch_id() if branch_id is _UNSET else branch_id
            interrupt = self._interrupt_by_id(interrupt_id)
            if interrupt is None:
                return None
            if resolved_branch_id is not None and interrupt.branch_id != resolved_branch_id:
                return None
            decision_record: JsonObject = {
                "decision": decision,
                "created_at": self._now(),
            }
            if response is not None:
                decision_record["response"] = response
            if edited_payload_dict:
                decision_record["edited_payload"] = edited_payload_dict
            resolved = replace(
                interrupt,
                status="resolved",
                decisions=(*interrupt.decisions, decision_record),
            )
            if self._connection is None:
                self._interrupts[interrupt_id] = replace(resolved)
                return replace(resolved)
            self._connection.execute(
                """
                update team_conversation_interrupts
                set status = ?, decisions_json = ?
                where team_id = ? and conversation_id = ? and id = ?
                """,
                (
                    resolved.status,
                    json.dumps(list(resolved.decisions), ensure_ascii=False),
                    self.team_id,
                    self.conversation_id,
                    interrupt_id,
                ),
            )
            self._connection.commit()
            return replace(resolved)

    def list_deliveries(self, *, branch_id: str | None | _UnsetType = _UNSET) -> list[ConversationDelivery]:
        with self._lock:
            resolved_branch_id = self.current_branch_id() if branch_id is _UNSET else branch_id
            if self._connection is None:
                return [
                    delivery
                    for delivery in self._deliveries
                    if resolved_branch_id is None or delivery.branch_id == resolved_branch_id
                ]
            clauses = ["team_id = ?", "conversation_id = ?"]
            params: list[object] = [self.team_id, self.conversation_id]
            if resolved_branch_id is not None:
                clauses.append("branch_id = ?")
                params.append(resolved_branch_id)
            rows = self._connection.execute(
                f"""
                select
                    branch_id,
                    id,
                    agent_id,
                    run_id,
                    snapshot_seq,
                    status,
                    created_at,
                    completed_at,
                    error
                from team_conversation_deliveries
                where {" and ".join(clauses)}
                order by created_at asc, id asc
                """,
                tuple(params),
            ).fetchall()
            return [
                ConversationDelivery(
                    id=str(row[1]),
                    team_id=self.team_id,
                    conversation_id=self.conversation_id,
                    branch_id=str(row[0]),
                    agent_id=str(row[2]),
                    run_id=str(row[3]) if row[3] is not None else None,
                    snapshot_seq=int(row[4]) if row[4] is not None else None,
                    status=self._delivery_status(row[5]),
                    created_at=str(row[6]),
                    completed_at=str(row[7]) if row[7] is not None else None,
                    error=str(row[8]) if row[8] is not None else None,
                )
                for row in rows
            ]

    def _initialize_sqlite(self) -> None:
        connection = self._connection
        if connection is None:
            return
        connection.execute(
            """
            create table if not exists team_conversation_events (
                team_id text not null,
                conversation_id text not null,
                branch_id text not null default 'branch_main',
                logical_message_id text,
                version_parent_event_id text,
                parent_event_id text,
                frontier_before_event_id text,
                frontier_after_event_id text,
                seq integer not null,
                id text not null,
                created_at text not null,
                author_id text not null,
                author_kind text not null,
                content text not null,
                mentions_json text not null,
                source_thread_id text,
                source_message_id text,
                metadata_json text not null,
                primary key (team_id, conversation_id, seq),
                unique (team_id, conversation_id, id)
            )
            """
        )
        connection.execute(
            """
            create table if not exists team_conversation_files (
                team_id text not null,
                conversation_id text not null,
                event_id text not null,
                file_id text not null,
                filename text not null,
                uri text not null,
                media_type text,
                size_bytes integer,
                added_by text,
                primary key (team_id, conversation_id, event_id, file_id)
            )
            """
        )
        connection.execute(
            """
            create table if not exists team_conversation_agent_state (
                team_id text not null,
                conversation_id text not null,
                branch_id text not null default 'branch_main',
                agent_id text not null,
                last_delivered_seq integer not null,
                running integer not null,
                queued integer not null,
                queued_after_seq integer,
                current_run_id text,
                current_snapshot_seq integer,
                stop_requested integer not null,
                last_identity_refresh_seq integer not null,
                token_estimate_since_identity_refresh integer not null,
                primary key (team_id, conversation_id, branch_id, agent_id)
            )
            """
        )
        connection.execute(
            """
            create table if not exists team_conversation_deliveries (
                team_id text not null,
                conversation_id text not null,
                branch_id text not null default 'branch_main',
                id text not null,
                agent_id text not null,
                run_id text,
                snapshot_seq integer,
                status text not null,
                created_at text not null,
                completed_at text,
                error text,
                primary key (team_id, conversation_id, id)
            )
            """
        )
        connection.execute(
            """
            create table if not exists team_conversation_runs (
                team_id text not null,
                conversation_id text not null,
                id text not null,
                branch_id text not null default 'branch_main',
                agent_id text not null,
                logical_thread_key text,
                physical_thread_id text,
                status text not null,
                stop_kind text,
                snapshot_seq integer,
                started_at text not null,
                completed_at text,
                stable_checkpoint_id text,
                latest_checkpoint_id text,
                checkpoint_stability text not null,
                usable_for_fork integer not null,
                usable_for_continue integer not null,
                commit_state text not null,
                primary key (team_id, conversation_id, id)
            )
            """
        )
        connection.execute(
            """
            create table if not exists team_conversation_model_attempts (
                team_id text not null,
                conversation_id text not null,
                branch_id text not null default 'branch_main',
                id text not null,
                run_id text not null,
                agent_id text not null,
                provider text not null,
                model text not null,
                attempt_number integer not null,
                max_attempts integer not null,
                timeout_mode text not null,
                timeout_seconds real not null,
                started_at text not null,
                completed_at text,
                status text not null,
                normalized_failure_code text,
                provider_error_type text,
                primary key (team_id, conversation_id, id)
            )
            """
        )
        connection.execute(
            """
            create table if not exists team_conversation_runtime_state (
                team_id text not null,
                conversation_id text not null,
                mention_hook_enabled integer not null,
                max_cascade_turns integer,
                primary key (team_id, conversation_id)
            )
            """
        )
        connection.execute(
            """
            create table if not exists team_conversation_history_schema (
                team_id text not null,
                conversation_id text not null,
                history_schema_version text not null,
                initialized_at text not null,
                primary key (team_id, conversation_id)
            )
            """
        )
        connection.execute(
            """
            create table if not exists team_conversation_branches (
                team_id text not null,
                conversation_id text not null,
                id text not null,
                label text not null,
                parent_branch_id text,
                origin_checkpoint_id text,
                origin_event_id text,
                origin_logical_message_id text,
                origin_previous_event_id text,
                origin_event_seq integer,
                created_at text not null,
                current integer not null,
                head_checkpoint_id text,
                archived_at text,
                primary key (team_id, conversation_id, id)
            )
            """
        )
        connection.execute(
            """
            create table if not exists team_conversation_branch_threads (
                team_id text not null,
                conversation_id text not null,
                branch_id text not null,
                logical_thread_key text not null,
                physical_thread_id text not null,
                forked_from_branch_id text,
                forked_from_thread_id text,
                forked_from_checkpoint_id text,
                created_by_commit_id text,
                status text not null,
                primary key (team_id, conversation_id, branch_id, logical_thread_key)
            )
            """
        )
        self._ensure_tool_call_edges_schema()
        connection.execute(
            """
            create table if not exists team_conversation_thread_frontiers (
                team_id text not null,
                conversation_id text not null,
                frontier_id text not null,
                branch_id text not null,
                event_id text not null,
                event_boundary text not null,
                logical_thread_key text not null,
                physical_thread_id text not null,
                checkpoint_id text,
                run_id text,
                parent_logical_thread_key text,
                usable_for_fork integer not null,
                usable_for_continue integer not null,
                created_at text not null,
                primary key (team_id, conversation_id, frontier_id, event_boundary, logical_thread_key)
            )
            """
        )
        connection.execute(
            """
            create table if not exists team_conversation_control_events (
                team_id text not null,
                conversation_id text not null,
                id text not null,
                branch_id text not null,
                logical_thread_key text not null,
                physical_thread_id text not null,
                parent_run_id text,
                kind text not null,
                content text not null,
                created_at text not null,
                primary key (team_id, conversation_id, id)
            )
            """
        )
        connection.execute(
            """
            create table if not exists team_conversation_external_side_effects (
                team_id text not null,
                conversation_id text not null,
                id text not null,
                branch_id text not null,
                run_id text,
                agent_id text,
                tool_call_id text,
                kind text not null,
                target text not null,
                audit_payload_json text not null,
                not_rewindable integer not null,
                created_at text not null,
                primary key (team_id, conversation_id, id)
            )
            """
        )
        connection.execute(
            """
            create table if not exists team_conversation_studio_branch_ui_state (
                team_id text not null,
                conversation_id text not null,
                branch_id text not null,
                participant_id text not null,
                draft_content text not null,
                outbox_state_json text not null,
                editing_event_id text,
                selected_agent_id text,
                scroll_anchor_event_id text,
                updated_at text not null,
                primary key (team_id, conversation_id, branch_id, participant_id)
            )
            """
        )
        connection.execute(
            """
            create table if not exists team_conversation_interrupts (
                team_id text not null,
                conversation_id text not null,
                id text not null,
                branch_id text not null default 'branch_main',
                run_id text,
                agent_id text,
                checkpoint_id text,
                created_at text not null,
                kind text not null,
                payload_json text not null,
                status text not null,
                decisions_json text not null,
                primary key (team_id, conversation_id, id)
            )
            """
        )
        self._ensure_column("team_conversation_events", "branch_id", "text not null default 'branch_main'")
        self._ensure_column("team_conversation_events", "logical_message_id", "text")
        self._ensure_column("team_conversation_events", "version_parent_event_id", "text")
        self._ensure_column("team_conversation_events", "parent_event_id", "text")
        self._ensure_column("team_conversation_events", "frontier_before_event_id", "text")
        self._ensure_column("team_conversation_events", "frontier_after_event_id", "text")
        self._ensure_branch_scoped_agent_state()
        self._ensure_column("team_conversation_deliveries", "branch_id", "text not null default 'branch_main'")
        self._ensure_column("team_conversation_interrupts", "branch_id", "text not null default 'branch_main'")
        self._ensure_column("team_conversation_branches", "origin_event_id", "text")
        self._ensure_column("team_conversation_branches", "origin_logical_message_id", "text")
        self._ensure_column("team_conversation_branches", "origin_previous_event_id", "text")
        self._ensure_column("team_conversation_branches", "origin_event_seq", "integer")
        self._ensure_column("team_conversation_branches", "archived_at", "text")
        self._ensure_column("team_conversation_thread_frontiers", "run_id", "text")
        self._ensure_branch_aware_history_schema()
        connection.commit()
        self.reconcile_incomplete_commits()
        self.get_runtime_state()

    def _ensure_tool_call_edges_schema(self) -> None:
        connection = self._connection
        if connection is None:
            return
        if self._table_exists("tool_call_edges"):
            columns = {str(row[1]) for row in connection.execute("pragma table_info(tool_call_edges)").fetchall()}
            required_columns = {"team_id", "conversation_id", "id", "commit_id"}
            if not required_columns.issubset(columns):
                connection.execute("drop table tool_call_edges")
        connection.execute(
            """
            create table if not exists tool_call_edges (
                team_id text not null,
                conversation_id text not null,
                id text not null,
                commit_id text not null,
                branch_id text not null,
                parent_logical_thread_key text not null,
                parent_physical_thread_id text not null,
                relation_id text not null,
                target_agent_id text not null,
                child_logical_thread_key text not null,
                child_physical_thread_id text not null,
                run_id text,
                status text not null,
                primary key (team_id, conversation_id, id)
            )
            """
        )

    def _next_seq(self) -> int:
        if self._connection is None:
            return len(self._events) + 1
        row = self._connection.execute(
            """
            select max(seq)
            from team_conversation_events
            where team_id = ? and conversation_id = ?
            """,
            (self.team_id, self.conversation_id),
        ).fetchone()
        return int(row[0] or 0) + 1

    def _upsert_runtime_state(self, state: ConversationRuntimeState) -> None:
        if self._connection is None:
            return
        self._connection.execute(
            """
            insert into team_conversation_runtime_state (
                team_id,
                conversation_id,
                mention_hook_enabled,
                max_cascade_turns
            )
            values (?, ?, ?, ?)
            on conflict(team_id, conversation_id) do update set
                mention_hook_enabled = excluded.mention_hook_enabled,
                max_cascade_turns = excluded.max_cascade_turns
            """,
            (
                state.team_id,
                state.conversation_id,
                int(state.mention_hook_enabled),
                state.max_cascade_turns,
            ),
        )
        self._connection.commit()

    def _event_from_row(self, row: tuple[object, ...]) -> ConversationEvent:
        event_id = str(row[9])
        raw_mentions: object = json.loads(str(row[14] or "[]"))
        mentions = tuple(item for item in raw_mentions if isinstance(item, str)) if isinstance(raw_mentions, list) else ()
        raw_metadata: object = json.loads(str(row[17] or "{}"))
        return ConversationEvent(
            team_id=str(row[0]),
            conversation_id=str(row[1]),
            branch_id=str(row[2] or "branch_main"),
            logical_message_id=str(row[3]) if row[3] is not None else event_id,
            version_parent_event_id=str(row[4]) if row[4] is not None else None,
            parent_event_id=str(row[5]) if row[5] is not None else None,
            frontier_before_event_id=str(row[6]) if row[6] is not None else None,
            frontier_after_event_id=str(row[7]) if row[7] is not None else None,
            seq=int(row[8]),
            id=event_id,
            created_at=str(row[10]),
            author_id=str(row[11]),
            author_kind="agent" if row[12] == "agent" else "human",
            content=str(row[13] or ""),
            mentions=mentions,
            attachments=tuple(self._attachments_for(event_id)),
            source_thread_id=str(row[15]) if row[15] is not None else None,
            source_message_id=str(row[16]) if row[16] is not None else None,
            metadata=raw_metadata if is_json_object(raw_metadata) else {},
        )

    def _attachments_for(self, event_id: str) -> list[ConversationFileRef]:
        if self._connection is None:
            for event in self._events:
                if event.id == event_id:
                    return list(event.attachments)
            return []
        rows = self._connection.execute(
            """
            select file_id, filename, uri, media_type, size_bytes, added_by
            from team_conversation_files
            where team_id = ? and conversation_id = ? and event_id = ?
            order by file_id asc
            """,
            (self.team_id, self.conversation_id, event_id),
        ).fetchall()
        return [
            ConversationFileRef(
                id=str(row[0]),
                filename=str(row[1]),
                uri=str(row[2]),
                media_type=str(row[3]) if row[3] is not None else None,
                size_bytes=int(row[4]) if row[4] is not None else None,
                added_by=str(row[5]) if row[5] is not None else None,
            )
            for row in rows
        ]

    def _branch_from_row(self, row: tuple[object, ...]) -> ConversationBranch:
        return ConversationBranch(
            id=str(row[0]),
            team_id=self.team_id,
            conversation_id=self.conversation_id,
            label=str(row[1]),
            parent_branch_id=str(row[2]) if row[2] is not None else None,
            origin_checkpoint_id=str(row[3]) if row[3] is not None else None,
            origin_event_id=str(row[4]) if row[4] is not None else None,
            origin_logical_message_id=str(row[5]) if row[5] is not None else None,
            origin_previous_event_id=str(row[6]) if row[6] is not None else None,
            origin_event_seq=int(row[7]) if row[7] is not None else None,
            created_at=str(row[8]),
            current=bool(row[9]),
            status="persisted",
            head_checkpoint_id=str(row[10]) if row[10] is not None else None,
            archived_at=str(row[11]) if len(row) > 11 and row[11] is not None else None,
        )

    def _branch_thread_from_row(self, row: tuple[object, ...]) -> ConversationBranchThread:
        return ConversationBranchThread(
            team_id=self.team_id,
            conversation_id=self.conversation_id,
            branch_id=str(row[0]),
            logical_thread_key=str(row[1]),
            physical_thread_id=str(row[2]),
            forked_from_branch_id=str(row[3]) if row[3] is not None else None,
            forked_from_thread_id=str(row[4]) if row[4] is not None else None,
            forked_from_checkpoint_id=str(row[5]) if row[5] is not None else None,
            created_by_commit_id=str(row[6]) if row[6] is not None else None,
            status=self._branch_thread_status(row[7]),
        )

    def _thread_frontier_from_row(self, row: tuple[object, ...]) -> ThreadFrontier:
        return ThreadFrontier(
            frontier_id=str(row[0]),
            team_id=self.team_id,
            conversation_id=self.conversation_id,
            branch_id=str(row[1]),
            event_id=str(row[2]),
            event_boundary=self._thread_frontier_boundary(row[3]),
            logical_thread_key=str(row[4]),
            physical_thread_id=str(row[5]),
            checkpoint_id=str(row[6]) if row[6] is not None else None,
            run_id=str(row[7]) if row[7] is not None else None,
            parent_logical_thread_key=str(row[8]) if row[8] is not None else None,
            usable_for_fork=bool(row[9]),
            usable_for_continue=bool(row[10]),
            created_at=str(row[11]),
        )

    def _control_event_from_row(self, row: tuple[object, ...]) -> ConversationControlEvent:
        return ConversationControlEvent(
            id=str(row[0]),
            team_id=self.team_id,
            conversation_id=self.conversation_id,
            branch_id=str(row[1]),
            logical_thread_key=str(row[2]),
            physical_thread_id=str(row[3]),
            parent_run_id=str(row[4]) if row[4] is not None else None,
            kind=str(row[5]),
            content=str(row[6] or ""),
            created_at=str(row[7]),
        )

    def _external_side_effect_from_row(self, row: tuple[object, ...]) -> ExternalSideEffect:
        raw_payload: object = json.loads(str(row[7] or "{}"))
        return ExternalSideEffect(
            id=str(row[0]),
            team_id=self.team_id,
            conversation_id=self.conversation_id,
            branch_id=str(row[1]),
            run_id=str(row[2]) if row[2] is not None else None,
            agent_id=str(row[3]) if row[3] is not None else None,
            tool_call_id=str(row[4]) if row[4] is not None else None,
            kind=str(row[5]),
            target=str(row[6]),
            audit_payload=raw_payload if is_json_object(raw_payload) else {},
            not_rewindable=bool(row[8]),
            created_at=str(row[9]),
        )

    def _studio_branch_ui_state_from_row(self, row: tuple[object, ...]) -> StudioBranchUiState:
        raw_outbox_state: object = json.loads(str(row[3] or "[]"))
        return StudioBranchUiState(
            team_id=self.team_id,
            conversation_id=self.conversation_id,
            branch_id=str(row[0]),
            participant_id=str(row[1]),
            draft_content=str(row[2] or ""),
            outbox_state=raw_outbox_state if is_json_value(raw_outbox_state) else [],
            editing_event_id=str(row[4]) if row[4] is not None else None,
            selected_agent_id=str(row[5]) if row[5] is not None else None,
            scroll_anchor_event_id=str(row[6]) if row[6] is not None else None,
            updated_at=str(row[7]),
        )

    def _run_from_row(self, row: tuple[object, ...]) -> ConversationRun:
        return ConversationRun(
            id=str(row[0]),
            team_id=self.team_id,
            conversation_id=self.conversation_id,
            branch_id=str(row[1] or "branch_main"),
            agent_id=str(row[2]),
            logical_thread_key=str(row[3]) if row[3] is not None else None,
            physical_thread_id=str(row[4]) if row[4] is not None else None,
            status=self._run_status(row[5]),
            stop_kind=str(row[6]) if row[6] is not None else None,
            snapshot_seq=int(row[7]) if row[7] is not None else None,
            started_at=str(row[8]),
            completed_at=str(row[9]) if row[9] is not None else None,
            stable_checkpoint_id=str(row[10]) if row[10] is not None else None,
            latest_checkpoint_id=str(row[11]) if row[11] is not None else None,
            checkpoint_stability=self._checkpoint_stability(row[12]),
            usable_for_fork=bool(row[13]),
            usable_for_continue=bool(row[14]),
            commit_state=self._run_commit_state(row[15]),
        )

    def _model_attempt_from_row(self, row: tuple[object, ...]) -> ConversationModelAttempt:
        return ConversationModelAttempt(
            id=str(row[1]),
            team_id=self.team_id,
            conversation_id=self.conversation_id,
            branch_id=str(row[0] or "branch_main"),
            run_id=str(row[2]),
            agent_id=str(row[3]),
            provider=str(row[4]),
            model=str(row[5]),
            attempt_number=int(row[6]),
            max_attempts=int(row[7]),
            timeout_mode=str(row[8]),
            timeout_seconds=float(row[9]),
            started_at=str(row[10]),
            completed_at=str(row[11]) if row[11] is not None else None,
            status=self._model_attempt_status(row[12]),
            normalized_failure_code=str(row[13]) if row[13] is not None else None,
            provider_error_type=str(row[14]) if row[14] is not None else None,
        )

    def _complete_run_record_from_delivery(self, delivery: ConversationDelivery) -> None:
        if delivery.run_id is None:
            return

        run = self.get_run(delivery.run_id)
        if run is not None and run.commit_state == "orphaned":
            return
        if run is None:
            run = ConversationRun(
                id=delivery.run_id,
                team_id=self.team_id,
                conversation_id=self.conversation_id,
                branch_id=delivery.branch_id,
                agent_id=delivery.agent_id,
                status="running",
                snapshot_seq=delivery.snapshot_seq,
                started_at=delivery.created_at,
            )

        stable_terminal = delivery.status in {"empty", "interrupted", "skipped", "stopped", "success"}
        latest_checkpoint_id = self.latest_checkpoint_id(run.physical_thread_id) if run.physical_thread_id else None
        stable_checkpoint_id = latest_checkpoint_id if stable_terminal and latest_checkpoint_id is not None else run.stable_checkpoint_id
        checkpoint_stability: CheckpointStability
        if stable_checkpoint_id is not None and stable_terminal:
            checkpoint_stability = "stable"
        elif latest_checkpoint_id is not None:
            checkpoint_stability = "unstable"
        else:
            checkpoint_stability = "unknown"
        usable = stable_terminal and stable_checkpoint_id is not None
        completed_run = replace(
            run,
            status=self._run_status_from_delivery(delivery.status),
            stop_kind="cooperative" if delivery.status == "stopped" else run.stop_kind,
            snapshot_seq=delivery.snapshot_seq if delivery.snapshot_seq is not None else run.snapshot_seq,
            completed_at=delivery.completed_at or self._now(),
            stable_checkpoint_id=stable_checkpoint_id,
            latest_checkpoint_id=latest_checkpoint_id,
            checkpoint_stability=checkpoint_stability,
            usable_for_fork=usable,
            usable_for_continue=usable,
            commit_state="committed",
        )
        self._save_run(completed_run)
        self._record_terminal_run_frontier(completed_run, delivery)
        self._clear_run_agent_state(run, delivery)

    def _record_terminal_run_frontier(self, run: ConversationRun, delivery: ConversationDelivery) -> None:
        if delivery.status == "success" or run.logical_thread_key is None or run.physical_thread_id is None:
            return
        event = self._latest_visible_event_through_seq(delivery.branch_id, delivery.snapshot_seq)
        checkpoint_id = run.stable_checkpoint_id or run.latest_checkpoint_id
        if event is None or event.frontier_after_event_id is None or checkpoint_id is None:
            return
        self.record_thread_frontier(
            frontier_id=event.frontier_after_event_id,
            branch_id=delivery.branch_id,
            event_id=event.id,
            event_boundary="after",
            logical_thread_key=run.logical_thread_key,
            physical_thread_id=run.physical_thread_id,
            checkpoint_id=checkpoint_id,
            run_id=run.id,
            usable_for_fork=run.usable_for_fork,
            usable_for_continue=run.usable_for_continue,
        )

    def _latest_visible_event_through_seq(self, branch_id: str, snapshot_seq: int | None) -> ConversationEvent | None:
        if snapshot_seq is None:
            return None
        events = self.list_events(through_seq=snapshot_seq, branch_id=branch_id)
        return events[-1] if events else None

    def _latest_delivery_for_run(self, run_id: str) -> ConversationDelivery | None:
        if self._connection is None:
            deliveries = [delivery for delivery in self._deliveries if delivery.run_id == run_id]
            deliveries.sort(key=lambda item: (item.completed_at or item.created_at, item.id))
            return replace(deliveries[-1]) if deliveries else None
        row = self._connection.execute(
            """
            select
                branch_id,
                id,
                agent_id,
                run_id,
                snapshot_seq,
                status,
                created_at,
                completed_at,
                error
            from team_conversation_deliveries
            where team_id = ? and conversation_id = ? and run_id = ?
            order by coalesce(completed_at, created_at) desc, id desc
            limit 1
            """,
            (self.team_id, self.conversation_id, run_id),
        ).fetchone()
        if row is None:
            return None
        return ConversationDelivery(
            id=str(row[1]),
            team_id=self.team_id,
            conversation_id=self.conversation_id,
            branch_id=str(row[0]),
            agent_id=str(row[2]),
            run_id=str(row[3]) if row[3] is not None else None,
            snapshot_seq=int(row[4]) if row[4] is not None else None,
            status=self._delivery_status(row[5]),
            created_at=str(row[6]),
            completed_at=str(row[7]) if row[7] is not None else None,
            error=str(row[8]) if row[8] is not None else None,
        )

    def _fail_running_model_attempts_for_run(self, run_id: str) -> int:
        attempts = [attempt for attempt in self.list_model_attempts(run_id=run_id) if attempt.status == "running"]
        for attempt in attempts:
            self.record_model_attempt_finished(
                attempt.id,
                status="failed",
                normalized_failure_code="process_interrupted",
                provider_error_type="ProcessInterrupted",
            )
        return len(attempts)

    def _orphan_run(self, run: ConversationRun) -> None:
        latest_checkpoint_id = self.latest_checkpoint_id(run.physical_thread_id) if run.physical_thread_id else run.latest_checkpoint_id
        self._save_run(
            replace(
                run,
                status="failed",
                stop_kind="incomplete-commit",
                completed_at=run.completed_at or self._now(),
                latest_checkpoint_id=latest_checkpoint_id,
                checkpoint_stability="unstable" if latest_checkpoint_id is not None else "unknown",
                stable_checkpoint_id=None,
                usable_for_fork=False,
                usable_for_continue=False,
                commit_state="orphaned",
            )
        )
        state = self.get_agent_state(run.agent_id, branch_id=run.branch_id)
        if state is not None and state.current_run_id == run.id:
            self.save_agent_state(replace(state, running=False, current_run_id=None, current_snapshot_seq=None, stop_requested=False))

    def _clear_run_agent_state(self, run: ConversationRun, delivery: ConversationDelivery) -> None:
        state = self.get_agent_state(run.agent_id, branch_id=run.branch_id)
        if state is None or state.current_run_id != run.id:
            return
        delivered_status = delivery.status in {"empty", "skipped", "success"}
        self.save_agent_state(
            replace(
                state,
                last_delivered_seq=(
                    max(state.last_delivered_seq, delivery.snapshot_seq)
                    if delivered_status and delivery.snapshot_seq is not None
                    else state.last_delivered_seq
                ),
                running=False,
                current_run_id=None,
                current_snapshot_seq=None,
                stop_requested=False,
            )
        )

    def _save_run(self, run: ConversationRun) -> None:
        if self._connection is None:
            self._runs[run.id] = replace(run)
            return
        self._connection.execute(
            """
            insert into team_conversation_runs (
                team_id,
                conversation_id,
                id,
                branch_id,
                agent_id,
                logical_thread_key,
                physical_thread_id,
                status,
                stop_kind,
                snapshot_seq,
                started_at,
                completed_at,
                stable_checkpoint_id,
                latest_checkpoint_id,
                checkpoint_stability,
                usable_for_fork,
                usable_for_continue,
                commit_state
            )
            values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            on conflict(team_id, conversation_id, id) do update set
                branch_id = excluded.branch_id,
                agent_id = excluded.agent_id,
                logical_thread_key = excluded.logical_thread_key,
                physical_thread_id = excluded.physical_thread_id,
                status = excluded.status,
                stop_kind = excluded.stop_kind,
                snapshot_seq = excluded.snapshot_seq,
                started_at = excluded.started_at,
                completed_at = excluded.completed_at,
                stable_checkpoint_id = excluded.stable_checkpoint_id,
                latest_checkpoint_id = excluded.latest_checkpoint_id,
                checkpoint_stability = excluded.checkpoint_stability,
                usable_for_fork = excluded.usable_for_fork,
                usable_for_continue = excluded.usable_for_continue,
                commit_state = excluded.commit_state
            """,
            (
                run.team_id,
                run.conversation_id,
                run.id,
                run.branch_id,
                run.agent_id,
                run.logical_thread_key,
                run.physical_thread_id,
                run.status,
                run.stop_kind,
                run.snapshot_seq,
                run.started_at,
                run.completed_at,
                run.stable_checkpoint_id,
                run.latest_checkpoint_id,
                run.checkpoint_stability,
                int(run.usable_for_fork),
                int(run.usable_for_continue),
                run.commit_state,
            ),
        )
        self._connection.commit()

    def _save_branch_thread(self, branch_thread: ConversationBranchThread) -> None:
        if self._connection is None:
            self._branch_threads[(branch_thread.branch_id, branch_thread.logical_thread_key)] = replace(branch_thread)
            return
        self._connection.execute(
            """
            insert into team_conversation_branch_threads (
                team_id,
                conversation_id,
                branch_id,
                logical_thread_key,
                physical_thread_id,
                forked_from_branch_id,
                forked_from_thread_id,
                forked_from_checkpoint_id,
                created_by_commit_id,
                status
            )
            values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            on conflict(team_id, conversation_id, branch_id, logical_thread_key) do update set
                physical_thread_id = excluded.physical_thread_id,
                forked_from_branch_id = excluded.forked_from_branch_id,
                forked_from_thread_id = excluded.forked_from_thread_id,
                forked_from_checkpoint_id = excluded.forked_from_checkpoint_id,
                created_by_commit_id = excluded.created_by_commit_id,
                status = excluded.status
            """,
            (
                branch_thread.team_id,
                branch_thread.conversation_id,
                branch_thread.branch_id,
                branch_thread.logical_thread_key,
                branch_thread.physical_thread_id,
                branch_thread.forked_from_branch_id,
                branch_thread.forked_from_thread_id,
                branch_thread.forked_from_checkpoint_id,
                branch_thread.created_by_commit_id,
                branch_thread.status,
            ),
        )
        self._connection.commit()

    def _fork_branch_thread_if_possible(
        self,
        *,
        branch_id: str,
        logical_thread_key: str,
        target_physical_thread_id: str,
    ) -> tuple[str | None, str | None, str | None]:
        if branch_id == "branch_main" or self._connection is None:
            return None, None, None
        branch = self._branch_by_id(branch_id)
        if branch is None or not branch.origin_checkpoint_id:
            return None, None, None
        parent_branch_id = branch.parent_branch_id or "branch_main"
        source_frontier = self.get_thread_frontier(
            frontier_id=branch.origin_checkpoint_id,
            branch_id=parent_branch_id,
            logical_thread_key=logical_thread_key,
        )
        if source_frontier is None:
            source_frontier = self._latest_thread_frontier_for_checkpoint(
                branch_id=parent_branch_id,
                logical_thread_key=logical_thread_key,
                checkpoint_id=branch.origin_checkpoint_id,
            )
        if source_frontier is None or not source_frontier.usable_for_fork or not source_frontier.checkpoint_id:
            return None, None, None
        ThreadForker(self._connection).fork_checkpoint(
            source_physical_thread_id=source_frontier.physical_thread_id,
            source_checkpoint_id=source_frontier.checkpoint_id,
            target_physical_thread_id=target_physical_thread_id,
        )
        return source_frontier.branch_id, source_frontier.physical_thread_id, source_frontier.checkpoint_id

    def _latest_thread_frontier_for_checkpoint(
        self,
        *,
        branch_id: str,
        logical_thread_key: str,
        checkpoint_id: str,
    ) -> ThreadFrontier | None:
        candidates = [
            frontier
            for frontier in self.list_thread_frontiers(branch_id=branch_id)
            if frontier.logical_thread_key == logical_thread_key
            and frontier.event_boundary == "after"
            and frontier.checkpoint_id == checkpoint_id
        ]
        return candidates[-1] if candidates else None

    def _branch_by_id(self, branch_id: str) -> ConversationBranch | None:
        if self._connection is None:
            branch = self._branches.get(branch_id)
            return replace(branch) if branch is not None else None
        row = self._connection.execute(
            """
            select
                id,
                label,
                parent_branch_id,
                origin_checkpoint_id,
                origin_event_id,
                origin_logical_message_id,
                origin_previous_event_id,
                origin_event_seq,
                created_at,
                current,
                head_checkpoint_id,
                archived_at
            from team_conversation_branches
            where team_id = ? and conversation_id = ? and id = ?
            """,
            (self.team_id, self.conversation_id, branch_id),
        ).fetchone()
        return self._branch_from_row(row) if row is not None else None

    def _interrupt_from_row(self, row: tuple[object, ...]) -> ConversationInterrupt:
        raw_payload: object = json.loads(str(row[7] or "{}"))
        raw_decisions: object = json.loads(str(row[9] or "[]"))
        decisions = tuple(item for item in raw_decisions if is_json_object(item)) if isinstance(raw_decisions, list) else ()
        return ConversationInterrupt(
            id=str(row[0]),
            team_id=self.team_id,
            conversation_id=self.conversation_id,
            branch_id=str(row[1] or "branch_main"),
            run_id=str(row[2]) if row[2] is not None else None,
            agent_id=str(row[3]) if row[3] is not None else None,
            checkpoint_id=str(row[4]) if row[4] is not None else None,
            created_at=str(row[5]),
            kind=self._interrupt_kind(row[6]),
            payload=raw_payload if is_json_object(raw_payload) else {},
            status=self._interrupt_status(row[8]),
            decisions=decisions,
        )

    def _interrupt_by_id(self, interrupt_id: str) -> ConversationInterrupt | None:
        if self._connection is None:
            interrupt = self._interrupts.get(interrupt_id)
            return replace(interrupt) if interrupt is not None else None
        row = self._connection.execute(
            """
            select
                id,
                branch_id,
                run_id,
                agent_id,
                checkpoint_id,
                created_at,
                kind,
                payload_json,
                status,
                decisions_json
            from team_conversation_interrupts
            where team_id = ? and conversation_id = ? and id = ?
            """,
            (self.team_id, self.conversation_id, interrupt_id),
        ).fetchone()
        return self._interrupt_from_row(row) if row is not None else None

    def _ensure_column(self, table: str, column: str, definition: str) -> None:
        if self._connection is None:
            return
        columns = {str(row[1]) for row in self._connection.execute(f"pragma table_info({table})").fetchall()}
        if column not in columns:
            self._connection.execute(f"alter table {table} add column {column} {definition}")

    def _ensure_branch_aware_history_schema(self) -> None:
        if self._connection is None:
            return
        row = self._connection.execute(
            """
            select history_schema_version
            from team_conversation_history_schema
            where team_id = ? and conversation_id = ?
            """,
            (self.team_id, self.conversation_id),
        ).fetchone()
        if row is not None and row[0] == _HISTORY_SCHEMA_VERSION:
            return
        if row is None and not self._has_persisted_conversation_history():
            self._upsert_history_schema_version()
            return

        self._delete_persisted_conversation_history()
        self._upsert_history_schema_version()

    def _has_persisted_conversation_history(self) -> bool:
        if self._connection is None:
            return False
        row = self._connection.execute(
            """
            select 1
            from team_conversation_events
            where team_id = ? and conversation_id = ?
            limit 1
            """,
            (self.team_id, self.conversation_id),
        ).fetchone()
        return row is not None

    def _delete_persisted_conversation_history(self) -> None:
        if self._connection is None:
            return
        tables = (
            "team_conversation_events",
            "team_conversation_files",
            "team_conversation_agent_state",
            "team_conversation_deliveries",
            "team_conversation_runs",
            "team_conversation_runtime_state",
            "team_conversation_branches",
            "team_conversation_branch_threads",
            "team_conversation_thread_frontiers",
            "team_conversation_control_events",
            "team_conversation_external_side_effects",
            "team_conversation_studio_branch_ui_state",
            "team_conversation_interrupts",
        )
        for table in tables:
            self._connection.execute(
                f"delete from {table} where team_id = ? and conversation_id = ?",
                (self.team_id, self.conversation_id),
            )

    def _upsert_history_schema_version(self) -> None:
        if self._connection is None:
            return
        self._connection.execute(
            """
            insert into team_conversation_history_schema (
                team_id,
                conversation_id,
                history_schema_version,
                initialized_at
            )
            values (?, ?, ?, ?)
            on conflict(team_id, conversation_id) do update set
                history_schema_version = excluded.history_schema_version,
                initialized_at = excluded.initialized_at
            """,
            (self.team_id, self.conversation_id, _HISTORY_SCHEMA_VERSION, self._now()),
        )

    def _ensure_branch_scoped_agent_state(self) -> None:
        if self._connection is None:
            return
        columns = {str(row[1]) for row in self._connection.execute("pragma table_info(team_conversation_agent_state)").fetchall()}
        if "branch_id" in columns:
            return
        self._connection.execute("alter table team_conversation_agent_state rename to team_conversation_agent_state_legacy")
        self._connection.execute(
            """
            create table team_conversation_agent_state (
                team_id text not null,
                conversation_id text not null,
                branch_id text not null default 'branch_main',
                agent_id text not null,
                last_delivered_seq integer not null,
                running integer not null,
                queued integer not null,
                queued_after_seq integer,
                current_run_id text,
                current_snapshot_seq integer,
                stop_requested integer not null,
                last_identity_refresh_seq integer not null,
                token_estimate_since_identity_refresh integer not null,
                primary key (team_id, conversation_id, branch_id, agent_id)
            )
            """
        )
        self._connection.execute(
            """
            insert into team_conversation_agent_state (
                team_id,
                conversation_id,
                branch_id,
                agent_id,
                last_delivered_seq,
                running,
                queued,
                queued_after_seq,
                current_run_id,
                current_snapshot_seq,
                stop_requested,
                last_identity_refresh_seq,
                token_estimate_since_identity_refresh
            )
            select
                team_id,
                conversation_id,
                'branch_main',
                agent_id,
                last_delivered_seq,
                running,
                queued,
                queued_after_seq,
                current_run_id,
                current_snapshot_seq,
                stop_requested,
                last_identity_refresh_seq,
                token_estimate_since_identity_refresh
            from team_conversation_agent_state_legacy
            """
        )
        self._connection.execute("drop table team_conversation_agent_state_legacy")

    def _resolved_branch_id(self, branch_id: str | None) -> str:
        return branch_id or self.current_branch_id()

    def _non_empty_participant_id(self, participant_id: str) -> str:
        participant = participant_id.strip()
        if not participant:
            raise ValueError("participant_id is required.")
        return participant

    def _default_studio_branch_ui_state(self, branch_id: str, participant_id: str) -> StudioBranchUiState:
        return StudioBranchUiState(
            team_id=self.team_id,
            conversation_id=self.conversation_id,
            branch_id=branch_id,
            participant_id=participant_id,
            updated_at=self._now(),
        )

    def _latest_visible_event(self, branch_id: str | None) -> ConversationEvent | None:
        events = self.list_events(branch_id=branch_id)
        return events[-1] if events else None

    def _event_visible_in_branch(self, event: ConversationEvent, branch_id: str | None) -> bool:
        return self._event_visible_in_branch_id(event, branch_id, set())

    def _event_visible_in_branch_id(
        self,
        event: ConversationEvent,
        branch_id: str | None,
        visited_branch_ids: set[str],
    ) -> bool:
        if branch_id is None:
            return True
        if branch_id == "branch_main":
            return event.branch_id == "branch_main"
        if branch_id in visited_branch_ids:
            return False
        visited_branch_ids.add(branch_id)
        if event.branch_id == branch_id:
            return True
        branch = self._branch_by_id(branch_id)
        if branch is None:
            return False
        if branch.origin_event_seq is not None and event.seq > branch.origin_event_seq:
            return False
        return self._event_visible_in_branch_id(event, branch.parent_branch_id or "branch_main", visited_branch_ids)

    def _initialize_branch_agent_states(self, branch: ConversationBranch) -> None:
        parent_branch_id = branch.parent_branch_id or "branch_main"
        for state in self.list_agent_states(branch_id=parent_branch_id):
            fork_seq = state.last_delivered_seq
            if branch.origin_event_seq is not None:
                fork_seq = min(fork_seq, branch.origin_event_seq)
            self.save_agent_state(
                AgentDeliveryState(
                    team_id=state.team_id,
                    conversation_id=state.conversation_id,
                    branch_id=branch.id,
                    agent_id=state.agent_id,
                    last_delivered_seq=fork_seq,
                    running=False,
                    queued=False,
                    queued_after_seq=None,
                    current_run_id=None,
                    current_snapshot_seq=None,
                    stop_requested=False,
                    last_identity_refresh_seq=(
                        min(state.last_identity_refresh_seq, fork_seq)
                        if branch.origin_event_seq is not None
                        else state.last_identity_refresh_seq
                    ),
                    token_estimate_since_identity_refresh=state.token_estimate_since_identity_refresh,
                )
            )

    def _set_current_branch(self, branch_id: str | None) -> None:
        if self._connection is None:
            self._current_branch_id = branch_id or "branch_main"
            for existing_id, branch in list(self._branches.items()):
                self._branches[existing_id] = replace(branch, current=existing_id == branch_id)
            return
        self._connection.execute(
            """
            update team_conversation_branches
            set current = 0
            where team_id = ? and conversation_id = ?
            """,
            (self.team_id, self.conversation_id),
        )
        if branch_id is not None:
            self._connection.execute(
                """
                update team_conversation_branches
                set current = 1
                where team_id = ? and conversation_id = ? and id = ?
                """,
                (self.team_id, self.conversation_id, branch_id),
            )
        self._connection.commit()

    def _delivery_status(self, value: object) -> DeliveryStatus:
        status = str(value)
        return cast(DeliveryStatus, status) if status in _DELIVERY_STATUSES else "failed"

    def _branch_thread_status(self, value: object) -> BranchThreadStatus:
        status = str(value)
        return cast(BranchThreadStatus, status) if status in _BRANCH_THREAD_STATUSES else "orphaned"

    def _thread_frontier_boundary(self, value: object) -> ThreadFrontierBoundary:
        boundary = str(value)
        return cast(ThreadFrontierBoundary, boundary) if boundary in _THREAD_FRONTIER_BOUNDARIES else "after"

    def _run_status(self, value: object) -> ConversationRunStatus:
        status = str(value)
        return cast(ConversationRunStatus, status) if status in _RUN_STATUSES else "failed"

    def _model_attempt_status(self, value: object) -> ModelAttemptStatus:
        status = str(value)
        return cast(ModelAttemptStatus, status) if status in _MODEL_ATTEMPT_STATUSES else "failed"

    def _run_status_from_delivery(self, status: DeliveryStatus) -> ConversationRunStatus:
        return cast(ConversationRunStatus, status) if status in _RUN_STATUSES else "failed"

    def _checkpoint_stability(self, value: object) -> CheckpointStability:
        stability = str(value)
        return cast(CheckpointStability, stability) if stability in _CHECKPOINT_STABILITIES else "unknown"

    def _run_commit_state(self, value: object) -> ConversationRunCommitState:
        commit_state = str(value)
        return cast(ConversationRunCommitState, commit_state) if commit_state in _RUN_COMMIT_STATES else "orphaned"

    def _table_exists(self, table_name: str) -> bool:
        if self._connection is None:
            return False
        row = self._connection.execute(
            "select 1 from sqlite_master where type = 'table' and name = ?",
            (table_name,),
        ).fetchone()
        return row is not None

    def _interrupt_kind(self, value: object) -> ConversationInterruptKind:
        kind = str(value)
        return cast(ConversationInterruptKind, kind) if kind in _INTERRUPT_KINDS else "review"

    def _interrupt_status(self, value: object) -> ConversationInterruptStatus:
        status = str(value)
        return cast(ConversationInterruptStatus, status) if status in _INTERRUPT_STATUSES else "pending"

    def _now(self) -> str:
        return datetime.now(timezone.utc).isoformat()
