from __future__ import annotations

import json
import sqlite3
import threading
import uuid
from dataclasses import replace
from datetime import datetime, timezone
from typing import cast

from src.type_defs import JsonMapping, is_json_object

from .agent_delivery_state import AgentDeliveryState
from .conversation_branch import ConversationBranch
from .conversation_delivery import ConversationDelivery, DeliveryStatus
from .conversation_event import AuthorKind, ConversationEvent
from .conversation_file_ref import ConversationFileRef
from .conversation_interrupt import (
    ConversationInterrupt,
    ConversationInterruptDecision,
    ConversationInterruptKind,
    ConversationInterruptStatus,
)
from .conversation_runtime_state import ConversationRuntimeState


class _UnsetType:
    pass


_UNSET = _UnsetType()
_DELIVERY_STATUSES: tuple[DeliveryStatus, ...] = (
    "cascade-limited",
    "empty",
    "failed",
    "ignored",
    "skipped",
    "stopped",
    "success",
)
_INTERRUPT_DECISIONS: tuple[ConversationInterruptDecision, ...] = ("approve", "reject", "edit", "respond")
_INTERRUPT_KINDS: tuple[ConversationInterruptKind, ...] = ("approve", "edit", "respond", "review")
_INTERRUPT_STATUSES: tuple[ConversationInterruptStatus, ...] = ("pending", "resolved")


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
        mentions: tuple[str, ...] = (),
        attachments: tuple[ConversationFileRef, ...] = (),
        source_thread_id: str | None = None,
        source_message_id: str | None = None,
        metadata: JsonMapping | None = None,
    ) -> ConversationEvent:
        with self._lock:
            seq = self._next_seq()
            event_id = f"evt_{uuid.uuid4().hex}"
            event = ConversationEvent(
                id=event_id,
                team_id=self.team_id,
                conversation_id=self.conversation_id,
                branch_id=self._resolved_branch_id(branch_id),
                logical_message_id=logical_message_id or event_id,
                version_parent_event_id=version_parent_event_id,
                parent_event_id=parent_event_id,
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
                values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    event.team_id,
                    event.conversation_id,
                    event.branch_id,
                    event.logical_message_id or event.id,
                    event.version_parent_event_id,
                    event.parent_event_id,
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
    ) -> AgentDeliveryState:
        with self._lock:
            state = self.ensure_agent_state(agent_id, branch_id=branch_id)
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
            self._connection.commit()
            return delivery

    def create_branch(
        self,
        *,
        label: str | None = None,
        origin_checkpoint_id: str | None = None,
        origin_event_id: str | None = None,
        origin_event_seq: int | None = None,
        head_checkpoint_id: str | None = None,
        parent_branch_id: str | None = None,
    ) -> ConversationBranch:
        branch = ConversationBranch(
            id=f"branch_{uuid.uuid4().hex}",
            team_id=self.team_id,
            conversation_id=self.conversation_id,
            label=label or f"Branch {len(self.list_branches()) + 1}",
            parent_branch_id=parent_branch_id or self.current_branch_id(),
            origin_checkpoint_id=origin_checkpoint_id,
            origin_event_id=origin_event_id,
            origin_event_seq=origin_event_seq,
            created_at=self._now(),
            current=False,
            status="persisted",
            head_checkpoint_id=head_checkpoint_id,
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
                    origin_event_seq,
                    created_at,
                    current,
                    head_checkpoint_id
                )
                values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    branch.team_id,
                    branch.conversation_id,
                    branch.id,
                    branch.label,
                    branch.parent_branch_id,
                    branch.origin_checkpoint_id,
                    branch.origin_event_id,
                    branch.origin_event_seq,
                    branch.created_at,
                    int(branch.current),
                    branch.head_checkpoint_id,
                ),
            )
            self._connection.commit()
            self._initialize_branch_agent_states(branch)
            return replace(branch)

    def list_branches(self) -> list[ConversationBranch]:
        with self._lock:
            if self._connection is None:
                return [replace(self._branches[branch_id]) for branch_id in sorted(self._branches)]
            rows = self._connection.execute(
                """
                select
                    id,
                    label,
                    parent_branch_id,
                    origin_checkpoint_id,
                    origin_event_id,
                    origin_event_seq,
                    created_at,
                    current,
                    head_checkpoint_id
                from team_conversation_branches
                where team_id = ? and conversation_id = ?
                order by created_at asc, id asc
                """,
                (self.team_id, self.conversation_id),
            ).fetchall()
            return [self._branch_from_row(row) for row in rows]

    def current_branch_id(self) -> str:
        with self._lock:
            if self._connection is None:
                return self._current_branch_id
            row = self._connection.execute(
                """
                select id
                from team_conversation_branches
                where team_id = ? and conversation_id = ? and current = 1
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
                if branch is None:
                    return None
                self._set_current_branch(branch_id)
                return replace(self._branches[branch_id])
            branch = self._branch_by_id(branch_id)
            if branch is None:
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
    ) -> ConversationInterrupt:
        if kind not in _INTERRUPT_KINDS:
            raise ValueError("interrupt kind is not supported.")
        payload_dict = dict(payload or {})
        if not is_json_object(payload_dict):
            raise ValueError("interrupt payload must be JSON-serializable.")
        interrupt = ConversationInterrupt(
            id=interrupt_id or f"interrupt_{uuid.uuid4().hex}",
            team_id=self.team_id,
            conversation_id=self.conversation_id,
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
                    run_id,
                    agent_id,
                    checkpoint_id,
                    created_at,
                    kind,
                    payload_json,
                    status,
                    decisions_json
                )
                values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    interrupt.team_id,
                    interrupt.conversation_id,
                    interrupt.id,
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

    def list_interrupts(self, *, active_only: bool = True) -> list[ConversationInterrupt]:
        with self._lock:
            if self._connection is None:
                interrupts = list(self._interrupts.values())
                if active_only:
                    interrupts = [interrupt for interrupt in interrupts if interrupt.status == "pending"]
                return [replace(interrupt) for interrupt in sorted(interrupts, key=lambda item: (item.created_at, item.id))]
            clauses = ["team_id = ?", "conversation_id = ?"]
            params: list[object] = [self.team_id, self.conversation_id]
            if active_only:
                clauses.append("status = ?")
                params.append("pending")
            rows = self._connection.execute(
                f"""
                select
                    id,
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
    ) -> ConversationInterrupt | None:
        if decision not in _INTERRUPT_DECISIONS:
            raise ValueError("interrupt decision is not supported.")
        edited_payload_dict = dict(edited_payload or {})
        if not is_json_object(edited_payload_dict):
            raise ValueError("interrupt edited_payload must be JSON-serializable.")
        with self._lock:
            interrupt = self._interrupt_by_id(interrupt_id)
            if interrupt is None:
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
            create table if not exists team_conversation_branches (
                team_id text not null,
                conversation_id text not null,
                id text not null,
                label text not null,
                parent_branch_id text,
                origin_checkpoint_id text,
                origin_event_id text,
                origin_event_seq integer,
                created_at text not null,
                current integer not null,
                head_checkpoint_id text,
                primary key (team_id, conversation_id, id)
            )
            """
        )
        connection.execute(
            """
            create table if not exists team_conversation_interrupts (
                team_id text not null,
                conversation_id text not null,
                id text not null,
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
        self._ensure_branch_scoped_agent_state()
        self._ensure_column("team_conversation_deliveries", "branch_id", "text not null default 'branch_main'")
        self._ensure_column("team_conversation_branches", "origin_event_id", "text")
        self._ensure_column("team_conversation_branches", "origin_event_seq", "integer")
        connection.commit()
        self.get_runtime_state()

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
        event_id = str(row[7])
        raw_mentions: object = json.loads(str(row[12] or "[]"))
        mentions = tuple(item for item in raw_mentions if isinstance(item, str)) if isinstance(raw_mentions, list) else ()
        raw_metadata: object = json.loads(str(row[15] or "{}"))
        return ConversationEvent(
            team_id=str(row[0]),
            conversation_id=str(row[1]),
            branch_id=str(row[2] or "branch_main"),
            logical_message_id=str(row[3]) if row[3] is not None else event_id,
            version_parent_event_id=str(row[4]) if row[4] is not None else None,
            parent_event_id=str(row[5]) if row[5] is not None else None,
            seq=int(row[6]),
            id=event_id,
            created_at=str(row[8]),
            author_id=str(row[9]),
            author_kind="agent" if row[10] == "agent" else "human",
            content=str(row[11] or ""),
            mentions=mentions,
            attachments=tuple(self._attachments_for(event_id)),
            source_thread_id=str(row[13]) if row[13] is not None else None,
            source_message_id=str(row[14]) if row[14] is not None else None,
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
            origin_event_seq=int(row[5]) if row[5] is not None else None,
            created_at=str(row[6]),
            current=bool(row[7]),
            status="persisted",
            head_checkpoint_id=str(row[8]) if row[8] is not None else None,
        )

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
                origin_event_seq,
                created_at,
                current,
                head_checkpoint_id
            from team_conversation_branches
            where team_id = ? and conversation_id = ? and id = ?
            """,
            (self.team_id, self.conversation_id, branch_id),
        ).fetchone()
        return self._branch_from_row(row) if row is not None else None

    def _interrupt_from_row(self, row: tuple[object, ...]) -> ConversationInterrupt:
        raw_payload: object = json.loads(str(row[6] or "{}"))
        raw_decisions: object = json.loads(str(row[8] or "[]"))
        decisions = tuple(item for item in raw_decisions if is_json_object(item)) if isinstance(raw_decisions, list) else ()
        return ConversationInterrupt(
            id=str(row[0]),
            team_id=self.team_id,
            conversation_id=self.conversation_id,
            run_id=str(row[1]) if row[1] is not None else None,
            agent_id=str(row[2]) if row[2] is not None else None,
            checkpoint_id=str(row[3]) if row[3] is not None else None,
            created_at=str(row[4]),
            kind=self._interrupt_kind(row[5]),
            payload=raw_payload if is_json_object(raw_payload) else {},
            status=self._interrupt_status(row[7]),
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

    def _interrupt_kind(self, value: object) -> ConversationInterruptKind:
        kind = str(value)
        return cast(ConversationInterruptKind, kind) if kind in _INTERRUPT_KINDS else "review"

    def _interrupt_status(self, value: object) -> ConversationInterruptStatus:
        status = str(value)
        return cast(ConversationInterruptStatus, status) if status in _INTERRUPT_STATUSES else "pending"

    def _now(self) -> str:
        return datetime.now(timezone.utc).isoformat()
