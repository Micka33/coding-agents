from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from langgraph.checkpoint.memory import MemorySaver

from coding_agents.checkpoints import create_checkpointer_handle
from coding_agents.config import AgentTeamConfig


class CheckpointerFactoryTests(unittest.TestCase):
    def test_memory_checkpointer_handle_is_process_local_and_closable(self) -> None:
        handle = create_checkpointer_handle(AgentTeamConfig(checkpointer_backend="memory"))

        self.assertEqual(handle.backend, "memory")
        self.assertEqual(handle.location, "process memory")
        self.assertIsInstance(handle.checkpointer, MemorySaver)
        handle.close()

    def test_sqlite_checkpointer_creates_parent_directory_and_checkpoint_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            checkpoint_path = Path("state/checkpoints.sqlite")
            handle = create_checkpointer_handle(
                AgentTeamConfig(
                    root_dir=root,
                    checkpointer_backend="sqlite",
                    sqlite_checkpoint_path=checkpoint_path,
                )
            )
            try:
                expected_path = root / checkpoint_path
                self.assertEqual(handle.backend, "sqlite")
                self.assertEqual(handle.location, str(expected_path))
                self.assertTrue(expected_path.parent.is_dir())
                self.assertTrue(expected_path.exists())
            finally:
                handle.close()

    def test_postgres_checkpointer_requires_configured_url(self) -> None:
        with self.assertRaisesRegex(ValueError, "CODING_AGENTS_POSTGRES_URL"):
            create_checkpointer_handle(
                AgentTeamConfig(
                    checkpointer_backend="postgres",
                    postgres_checkpoint_url=None,
                )
            )


if __name__ == "__main__":
    unittest.main()
