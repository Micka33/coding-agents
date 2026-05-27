from __future__ import annotations

import sqlite3
import tempfile
import unittest
from pathlib import Path

from webui.server import CheckpointHistoryReader


class WebUiServerTests(unittest.TestCase):
    def test_build_state_uses_runtime_manifest_lanes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            db_path = Path(tmp_dir) / "checkpoints.sqlite"
            with sqlite3.connect(db_path) as conn:
                self._create_checkpoint_tables(conn)
                self._create_manifest_tables(conn)
                self._insert_checkpoint(conn, "hello-world-smoke-2", "0001")
                self._insert_checkpoint(
                    conn,
                    "hello-world-smoke-2:german-speaker:ask_english_speaker:english-speaker",
                    "0002",
                )
                self._insert_hello_world_manifest(conn)

            state = CheckpointHistoryReader(db_path).build_state("hello-world-smoke-2")

        self.assertEqual(state["activeThreadId"], "hello-world-smoke-2")
        self.assertEqual([thread["id"] for thread in state["threads"]], ["hello-world-smoke-2"])
        self.assertEqual(
            [agent["id"] for agent in state["agents"]],
            [
                "german-speaker",
                "english-speaker",
            ],
        )
        self.assertEqual(
            state["agents"][1]["threadId"],
            "hello-world-smoke-2:german-speaker:ask_english_speaker:english-speaker",
        )
        self.assertTrue(state["agents"][1]["exists"])
        self.assertIn("task-subagent-type:translator", [lane["id"] for lane in state["runtimeLanes"]])

    def _create_checkpoint_tables(self, conn: sqlite3.Connection) -> None:
        conn.execute(
            """
            CREATE TABLE checkpoints (
                thread_id TEXT NOT NULL,
                checkpoint_ns TEXT NOT NULL DEFAULT '',
                checkpoint_id TEXT NOT NULL,
                parent_checkpoint_id TEXT,
                type TEXT,
                checkpoint BLOB,
                metadata BLOB,
                PRIMARY KEY (thread_id, checkpoint_ns, checkpoint_id)
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE writes (
                thread_id TEXT NOT NULL,
                checkpoint_ns TEXT NOT NULL DEFAULT '',
                checkpoint_id TEXT NOT NULL,
                task_id TEXT NOT NULL,
                idx INTEGER NOT NULL,
                channel TEXT NOT NULL,
                type TEXT,
                value BLOB,
                PRIMARY KEY (thread_id, checkpoint_ns, checkpoint_id, task_id, idx)
            )
            """
        )

    def _create_manifest_tables(self, conn: sqlite3.Connection) -> None:
        conn.execute(
            """
            CREATE TABLE team_runtime_manifests (
                team_id TEXT PRIMARY KEY,
                manifest_version INTEGER NOT NULL,
                created_at TEXT NOT NULL,
                manifest_json TEXT NOT NULL
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE team_runtime_lanes (
                team_id TEXT NOT NULL,
                lane_id TEXT NOT NULL,
                kind TEXT NOT NULL,
                agent_id TEXT,
                agent_name TEXT,
                source_agent_id TEXT,
                target_agent_id TEXT,
                tool_name TEXT,
                thread_id_pattern TEXT,
                PRIMARY KEY (team_id, lane_id)
            )
            """
        )

    def _insert_checkpoint(self, conn: sqlite3.Connection, thread_id: str, checkpoint_id: str) -> None:
        conn.execute(
            """
            INSERT INTO checkpoints (thread_id, checkpoint_ns, checkpoint_id, parent_checkpoint_id, type, checkpoint, metadata)
            VALUES (?, '', ?, NULL, NULL, NULL, NULL)
            """,
            (thread_id, checkpoint_id),
        )

    def _insert_hello_world_manifest(self, conn: sqlite3.Connection) -> None:
        conn.execute(
            """
            INSERT INTO team_runtime_manifests (team_id, manifest_version, created_at, manifest_json)
            VALUES ('hello-world', 1, '2026-05-27T00:00:00Z', '{}')
            """
        )
        lanes = [
            (
                "entrypoint:german-speaker",
                "entrypoint",
                "german-speaker",
                "german-speaker",
                None,
                None,
                None,
                "{parent_thread_id}",
            ),
            (
                "relation:german-speaker:ask_english_speaker:english-speaker",
                "tool-relation",
                "english-speaker",
                "english-speaker",
                "german-speaker",
                "english-speaker",
                "ask_english_speaker",
                "{parent_thread_id}:german-speaker:ask_english_speaker:english-speaker",
            ),
            (
                "relation:english-speaker:ask_german_speaker:german-speaker",
                "tool-relation",
                "german-speaker",
                "german-speaker",
                "english-speaker",
                "german-speaker",
                "ask_german_speaker",
                "{parent_thread_id}:english-speaker:ask_german_speaker:german-speaker",
            ),
            (
                "task-subagent-type:translator",
                "task-subagent-type",
                "translator",
                "translator",
                None,
                "translator",
                None,
                None,
            ),
        ]
        conn.executemany(
            """
            INSERT INTO team_runtime_lanes (
                team_id,
                lane_id,
                kind,
                agent_id,
                agent_name,
                source_agent_id,
                target_agent_id,
                tool_name,
                thread_id_pattern
            )
            VALUES ('hello-world', ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            lanes,
        )


if __name__ == "__main__":
    unittest.main()
