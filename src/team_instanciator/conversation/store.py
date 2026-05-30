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
from .conversation_delivery import ConversationDelivery, DeliveryStatus
from .conversation_event import AuthorKind, ConversationEvent
from .conversation_file_ref import ConversationFileRef
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
        self._agent_states: dict[str, AgentDeliveryState] = {}
        self._deliveries: list[ConversationDelivery] = []
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
        mentions: tuple[str, ...] = (),
        attachments: tuple[ConversationFileRef, ...] = (),
        source_thread_id: str | None = None,
        source_message_id: str | None = None,
        metadata: JsonMapping | None = None,
    ) -> ConversationEvent:
        with self._lock:
            seq = self._next_seq()
            event = ConversationEvent(
                id=f"evt_{uuid.uuid4().hex}",
                team_id=self.team_id,
                conversation_id=self.conversation_id,
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
                values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    event.team_id,
                    event.conversation_id,
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

    def list_events(self, *, after_seq: int = 0, through_seq: int | None = None) -> list[ConversationEvent]:
        with self._lock:
            if self._connection is None:
                return [
                    event
                    for event in self._events
                    if event.seq > after_seq and (through_seq is None or event.seq <= through_seq)
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
            return [self._event_from_row(row) for row in rows]

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

    def ensure_agent_state(self, agent_id: str) -> AgentDeliveryState:
        with self._lock:
            state = self.get_agent_state(agent_id)
            if state is not None:
                return state
            state = AgentDeliveryState(team_id=self.team_id, conversation_id=self.conversation_id, agent_id=agent_id)
            self.save_agent_state(state)
            return replace(state)

    def get_agent_state(self, agent_id: str) -> AgentDeliveryState | None:
        with self._lock:
            if self._connection is None:
                state = self._agent_states.get(agent_id)
                return replace(state) if state is not None else None
            row = self._connection.execute(
                """
                select
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
                where team_id = ? and conversation_id = ? and agent_id = ?
                """,
                (self.team_id, self.conversation_id, agent_id),
            ).fetchone()
            if row is None:
                return None
            return AgentDeliveryState(
                team_id=self.team_id,
                conversation_id=self.conversation_id,
                agent_id=agent_id,
                last_delivered_seq=int(row[0] or 0),
                running=bool(row[1]),
                queued=bool(row[2]),
                queued_after_seq=row[3],
                current_run_id=row[4],
                current_snapshot_seq=row[5],
                stop_requested=bool(row[6]),
                last_identity_refresh_seq=int(row[7] or 0),
                token_estimate_since_identity_refresh=int(row[8] or 0),
            )

    def list_agent_states(self) -> list[AgentDeliveryState]:
        with self._lock:
            if self._connection is None:
                return [replace(state) for state in self._agent_states.values()]
            rows = self._connection.execute(
                """
                select agent_id from team_conversation_agent_state
                where team_id = ? and conversation_id = ?
                order by agent_id asc
                """,
                (self.team_id, self.conversation_id),
            ).fetchall()
            return [state for row in rows if (state := self.get_agent_state(row[0])) is not None]

    def save_agent_state(self, state: AgentDeliveryState) -> None:
        with self._lock:
            if self._connection is None:
                self._agent_states[state.agent_id] = replace(state)
                return
            self._connection.execute(
                """
                insert into team_conversation_agent_state (
                    team_id,
                    conversation_id,
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
                values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                on conflict(team_id, conversation_id, agent_id) do update set
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

    def enqueue(self, agent_id: str, after_seq: int) -> AgentDeliveryState:
        with self._lock:
            state = self.ensure_agent_state(agent_id)
            queued_after_seq = max(after_seq, state.queued_after_seq or 0)
            updated = replace(state, queued=True, queued_after_seq=queued_after_seq)
            self.save_agent_state(updated)
            return updated

    def pending_idle_agent_ids(self, *, limit: int | None = None) -> list[str]:
        states = [
            state
            for state in self.list_agent_states()
            if state.queued and not state.running and not state.stop_requested
        ]
        states.sort(key=lambda item: (item.queued_after_seq or 0, item.agent_id))
        agent_ids = [state.agent_id for state in states]
        return agent_ids[:limit] if limit is not None else agent_ids

    def running_count(self) -> int:
        return sum(1 for state in self.list_agent_states() if state.running)

    def mark_run_started(self, agent_id: str, *, run_id: str, snapshot_seq: int) -> AgentDeliveryState:
        with self._lock:
            state = self.ensure_agent_state(agent_id)
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
    ) -> bool:
        with self._lock:
            state = self.ensure_agent_state(agent_id)
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

    def request_stop(self, agent_id: str) -> AgentDeliveryState:
        with self._lock:
            state = self.ensure_agent_state(agent_id)
            updated = replace(state, stop_requested=True)
            self.save_agent_state(updated)
            return updated

    def is_stop_requested(self, agent_id: str, run_id: str) -> bool:
        state = self.get_agent_state(agent_id)
        return bool(state and state.current_run_id == run_id and state.stop_requested)

    def record_delivery(
        self,
        *,
        agent_id: str,
        status: DeliveryStatus,
        run_id: str | None = None,
        snapshot_seq: int | None = None,
        error: str | None = None,
    ) -> ConversationDelivery:
        delivery = ConversationDelivery(
            id=f"dlv_{uuid.uuid4().hex}",
            team_id=self.team_id,
            conversation_id=self.conversation_id,
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
                    id,
                    agent_id,
                    run_id,
                    snapshot_seq,
                    status,
                    created_at,
                    completed_at,
                    error
                )
                values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    delivery.team_id,
                    delivery.conversation_id,
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

    def list_deliveries(self) -> list[ConversationDelivery]:
        with self._lock:
            if self._connection is None:
                return list(self._deliveries)
            rows = self._connection.execute(
                """
                select
                    id,
                    agent_id,
                    run_id,
                    snapshot_seq,
                    status,
                    created_at,
                    completed_at,
                    error
                from team_conversation_deliveries
                where team_id = ? and conversation_id = ?
                order by created_at asc, id asc
                """,
                (self.team_id, self.conversation_id),
            ).fetchall()
            return [
                ConversationDelivery(
                    id=str(row[0]),
                    team_id=self.team_id,
                    conversation_id=self.conversation_id,
                    agent_id=str(row[1]),
                    run_id=str(row[2]) if row[2] is not None else None,
                    snapshot_seq=int(row[3]) if row[3] is not None else None,
                    status=self._delivery_status(row[4]),
                    created_at=str(row[5]),
                    completed_at=str(row[6]) if row[6] is not None else None,
                    error=str(row[7]) if row[7] is not None else None,
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
                primary key (team_id, conversation_id, agent_id)
            )
            """
        )
        connection.execute(
            """
            create table if not exists team_conversation_deliveries (
                team_id text not null,
                conversation_id text not null,
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
        event_id = str(row[3])
        raw_mentions: object = json.loads(str(row[8] or "[]"))
        mentions = tuple(item for item in raw_mentions if isinstance(item, str)) if isinstance(raw_mentions, list) else ()
        raw_metadata: object = json.loads(str(row[11] or "{}"))
        return ConversationEvent(
            team_id=str(row[0]),
            conversation_id=str(row[1]),
            seq=int(row[2]),
            id=event_id,
            created_at=str(row[4]),
            author_id=str(row[5]),
            author_kind="agent" if row[6] == "agent" else "human",
            content=str(row[7] or ""),
            mentions=mentions,
            attachments=tuple(self._attachments_for(event_id)),
            source_thread_id=str(row[9]) if row[9] is not None else None,
            source_message_id=str(row[10]) if row[10] is not None else None,
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

    def _delivery_status(self, value: object) -> DeliveryStatus:
        status = str(value)
        return cast(DeliveryStatus, status) if status in _DELIVERY_STATUSES else "failed"

    def _now(self) -> str:
        return datetime.now(timezone.utc).isoformat()
