from __future__ import annotations

import sqlite3
import threading

from src.team_instanciator.runtime.tool_call_edge import ToolCallEdge, ToolCallEdgeStatus


class ToolCallEdgeRecorder:
    def __init__(self, connection: sqlite3.Connection | None = None) -> None:
        self._connection = connection
        self._lock = threading.RLock()
        if self._connection is not None:
            self._initialize_sqlite()

    def record_started(self, edge: ToolCallEdge) -> None:
        if self._connection is None:
            return
        with self._lock:
            self._connection.execute(
                """
                insert into tool_call_edges (
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
                )
                values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                on conflict(team_id, conversation_id, id) do update set
                    commit_id = excluded.commit_id,
                    branch_id = excluded.branch_id,
                    parent_logical_thread_key = excluded.parent_logical_thread_key,
                    parent_physical_thread_id = excluded.parent_physical_thread_id,
                    relation_id = excluded.relation_id,
                    target_agent_id = excluded.target_agent_id,
                    child_logical_thread_key = excluded.child_logical_thread_key,
                    child_physical_thread_id = excluded.child_physical_thread_id,
                    run_id = excluded.run_id,
                    status = excluded.status
                """,
                (
                    edge.team_id,
                    edge.conversation_id,
                    edge.id,
                    edge.commit_id,
                    edge.branch_id,
                    edge.parent_logical_thread_key,
                    edge.parent_physical_thread_id,
                    edge.relation_id,
                    edge.target_agent_id,
                    edge.child_logical_thread_key,
                    edge.child_physical_thread_id,
                    edge.run_id,
                    edge.status,
                ),
            )
            self._connection.commit()

    def record_finished(self, edge: ToolCallEdge, status: ToolCallEdgeStatus) -> None:
        if self._connection is None:
            return
        with self._lock:
            self._connection.execute(
                """
                update tool_call_edges
                set status = ?
                where team_id = ? and conversation_id = ? and id = ?
                """,
                (status, edge.team_id, edge.conversation_id, edge.id),
            )
            self._connection.commit()

    def _initialize_sqlite(self) -> None:
        if self._connection is None:
            return
        self._connection.execute(
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
        self._connection.commit()
