from __future__ import annotations

import sqlite3


class ThreadForker:
    def __init__(self, connection: sqlite3.Connection) -> None:
        self._connection = connection

    def fork_checkpoint(
        self,
        *,
        source_physical_thread_id: str,
        source_checkpoint_id: str,
        target_physical_thread_id: str,
        checkpoint_ns: str = "",
    ) -> list[str]:
        self._ensure_sqlite_checkpointer_schema()
        if self._thread_has_checkpoints(target_physical_thread_id, checkpoint_ns):
            raise ValueError("target physical thread already has checkpoints.")

        checkpoints = self._checkpoint_chain(source_physical_thread_id, source_checkpoint_id, checkpoint_ns)
        if not checkpoints:
            raise ValueError("source checkpoint does not exist.")

        for checkpoint in reversed(checkpoints):
            self._clone_checkpoint(checkpoint, target_physical_thread_id)
            self._clone_writes(
                source_physical_thread_id=source_physical_thread_id,
                source_checkpoint_id=str(checkpoint["checkpoint_id"]),
                target_physical_thread_id=target_physical_thread_id,
                checkpoint_ns=checkpoint_ns,
            )
        self._connection.commit()
        return [str(checkpoint["checkpoint_id"]) for checkpoint in reversed(checkpoints)]

    def _ensure_sqlite_checkpointer_schema(self) -> None:
        tables = {
            str(row[0])
            for row in self._connection.execute("select name from sqlite_master where type = 'table'").fetchall()
        }
        missing = {"checkpoints", "writes"} - tables
        if missing:
            raise ValueError("sqlite checkpointer tables are required to fork a checkpoint.")

    def _thread_has_checkpoints(self, thread_id: str, checkpoint_ns: str) -> bool:
        row = self._connection.execute(
            """
            select 1
            from checkpoints
            where thread_id = ? and checkpoint_ns = ?
            limit 1
            """,
            (thread_id, checkpoint_ns),
        ).fetchone()
        return row is not None

    def _checkpoint_chain(
        self,
        thread_id: str,
        checkpoint_id: str,
        checkpoint_ns: str,
    ) -> list[dict[str, object]]:
        chain: list[dict[str, object]] = []
        current_checkpoint_id: str | None = checkpoint_id
        while current_checkpoint_id:
            row = self._connection.execute(
                """
                select thread_id, checkpoint_ns, checkpoint_id, parent_checkpoint_id, type, checkpoint, metadata
                from checkpoints
                where thread_id = ? and checkpoint_ns = ? and checkpoint_id = ?
                """,
                (thread_id, checkpoint_ns, current_checkpoint_id),
            ).fetchone()
            if row is None:
                return []
            chain.append(
                {
                    "thread_id": row[0],
                    "checkpoint_ns": row[1],
                    "checkpoint_id": row[2],
                    "parent_checkpoint_id": row[3],
                    "type": row[4],
                    "checkpoint": row[5],
                    "metadata": row[6],
                }
            )
            current_checkpoint_id = str(row[3]) if row[3] is not None else None
        return chain

    def _clone_checkpoint(self, checkpoint: dict[str, object], target_physical_thread_id: str) -> None:
        self._connection.execute(
            """
            insert into checkpoints (
                thread_id,
                checkpoint_ns,
                checkpoint_id,
                parent_checkpoint_id,
                type,
                checkpoint,
                metadata
            )
            values (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                target_physical_thread_id,
                checkpoint["checkpoint_ns"],
                checkpoint["checkpoint_id"],
                checkpoint["parent_checkpoint_id"],
                checkpoint["type"],
                checkpoint["checkpoint"],
                checkpoint["metadata"],
            ),
        )

    def _clone_writes(
        self,
        *,
        source_physical_thread_id: str,
        source_checkpoint_id: str,
        target_physical_thread_id: str,
        checkpoint_ns: str,
    ) -> None:
        rows = self._connection.execute(
            """
            select task_id, idx, channel, type, value
            from writes
            where thread_id = ? and checkpoint_ns = ? and checkpoint_id = ?
            order by task_id asc, idx asc
            """,
            (source_physical_thread_id, checkpoint_ns, source_checkpoint_id),
        ).fetchall()
        for row in rows:
            self._connection.execute(
                """
                insert into writes (
                    thread_id,
                    checkpoint_ns,
                    checkpoint_id,
                    task_id,
                    idx,
                    channel,
                    type,
                    value
                )
                values (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    target_physical_thread_id,
                    checkpoint_ns,
                    source_checkpoint_id,
                    row[0],
                    row[1],
                    row[2],
                    row[3],
                    row[4],
                ),
            )
