from __future__ import annotations

import sqlite3
import unittest

from src.team_instanciator.runtime.thread_forker import ThreadForker


class ThreadForkerTests(unittest.TestCase):
    def test_fork_checkpoint_clones_checkpoint_chain_and_writes_without_descendants(self) -> None:
        connection = sqlite3.connect(":memory:")
        self._create_checkpoint_tables(connection)
        self._insert_checkpoint(connection, "source", "cp1", None)
        self._insert_checkpoint(connection, "source", "cp2", "cp1")
        self._insert_checkpoint(connection, "source", "cp3", "cp2")
        self._insert_write(connection, "source", "cp1", "cp1-write")
        self._insert_write(connection, "source", "cp2", "cp2-write")
        self._insert_write(connection, "source", "cp3", "cp3-write")

        cloned = ThreadForker(connection).fork_checkpoint(
            source_physical_thread_id="source",
            source_checkpoint_id="cp2",
            target_physical_thread_id="target",
        )

        target_checkpoints = connection.execute(
            """
            select checkpoint_id, parent_checkpoint_id
            from checkpoints
            where thread_id = 'target'
            order by checkpoint_id asc
            """
        ).fetchall()
        target_writes = connection.execute(
            """
            select checkpoint_id, value
            from writes
            where thread_id = 'target'
            order by checkpoint_id asc
            """
        ).fetchall()

        self.assertEqual(cloned, ["cp1", "cp2"])
        self.assertEqual(target_checkpoints, [("cp1", None), ("cp2", "cp1")])
        self.assertEqual(target_writes, [("cp1", b"cp1-write"), ("cp2", b"cp2-write")])
        self.assertIsNone(
            connection.execute(
                "select 1 from checkpoints where thread_id = 'target' and checkpoint_id = 'cp3'"
            ).fetchone()
        )

    def test_fork_checkpoint_refuses_missing_source_or_existing_target(self) -> None:
        connection = sqlite3.connect(":memory:")
        self._create_checkpoint_tables(connection)
        self._insert_checkpoint(connection, "source", "cp1", None)
        self._insert_checkpoint(connection, "target", "existing", None)

        for source_checkpoint_id, target_thread_id, message in (
            ("missing", "empty-target", "source checkpoint"),
            ("cp1", "target", "target physical thread"),
        ):
            with self.subTest(source_checkpoint_id=source_checkpoint_id, target_thread_id=target_thread_id):
                with self.assertRaisesRegex(ValueError, message):
                    ThreadForker(connection).fork_checkpoint(
                        source_physical_thread_id="source",
                        source_checkpoint_id=source_checkpoint_id,
                        target_physical_thread_id=target_thread_id,
                    )

    def _create_checkpoint_tables(self, connection: sqlite3.Connection) -> None:
        connection.execute(
            """
            create table checkpoints (
                thread_id text not null,
                checkpoint_ns text not null default '',
                checkpoint_id text not null,
                parent_checkpoint_id text,
                type text,
                checkpoint blob,
                metadata blob,
                primary key (thread_id, checkpoint_ns, checkpoint_id)
            )
            """
        )
        connection.execute(
            """
            create table writes (
                thread_id text not null,
                checkpoint_ns text not null default '',
                checkpoint_id text not null,
                task_id text not null,
                idx integer not null,
                channel text not null,
                type text,
                value blob,
                primary key (thread_id, checkpoint_ns, checkpoint_id, task_id, idx)
            )
            """
        )

    def _insert_checkpoint(
        self,
        connection: sqlite3.Connection,
        thread_id: str,
        checkpoint_id: str,
        parent_checkpoint_id: str | None,
    ) -> None:
        connection.execute(
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
            values (?, '', ?, ?, 'json', ?, ?)
            """,
            (thread_id, checkpoint_id, parent_checkpoint_id, b"checkpoint", b"metadata"),
        )

    def _insert_write(
        self,
        connection: sqlite3.Connection,
        thread_id: str,
        checkpoint_id: str,
        value: str,
    ) -> None:
        connection.execute(
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
            values (?, '', ?, 'task', 0, 'messages', 'bytes', ?)
            """,
            (thread_id, checkpoint_id, value.encode("utf-8")),
        )


if __name__ == "__main__":
    unittest.main()
