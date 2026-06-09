from __future__ import annotations

import asyncio
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from deepagents.backends.protocol import LsResult

from src.team_instanciator.backends.skill_filtering_backend import SkillFilteringBackend
from src.team_instanciator.factories.backend_factory import BackendFactory
from src.team_instanciator.factories.checkpointer_factory import CheckpointerFactory
from src.team_instanciator.runtime.checkpointer_handle import CheckpointerHandle
from src.team_instanciator.configuration.runtime_configuration import RuntimeConfiguration
from src.team_instanciator.errors.team_instanciator_error import TeamInstanciatorError
from tests.support import agent, defaults, team


class BackendFactoryTests(unittest.TestCase):
    def test_skill_filtering_backend_filters_sync_and_async_root_listing(self) -> None:
        class FakeBackend:
            delegated = "value"

            def ls(self, path: str) -> LsResult:
                return self._result(path)

            async def als(self, path: str) -> LsResult:
                return self._result(path)

            def _result(self, path: str) -> LsResult:
                if path == "/error":
                    return LsResult(error="boom")
                return LsResult(
                    entries=[
                        {"path": "/allowed/", "is_dir": True},
                        {"path": "/hidden/", "is_dir": True},
                        {"path": "/allowed.txt", "is_dir": False},
                    ]
                )

        backend = SkillFilteringBackend(FakeBackend(), ("allowed",))

        self.assertEqual(backend.delegated, "value")
        self.assertEqual([entry["path"] for entry in backend.ls("/").entries], ["/allowed/"])
        self.assertEqual(len(backend.ls("/nested").entries), 3)
        self.assertEqual(backend.ls("/error").error, "boom")
        self.assertEqual([entry["path"] for entry in asyncio.run(backend.als("/")).entries], ["/allowed/"])
        self.assertEqual(len(asyncio.run(backend.als("/nested")).entries), 3)

    def test_creates_filesystem_backend_by_default_and_composite_backend_for_local_shell_agents(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            team_config = team(working_directory=tmp, load_cwd=tmp, team_defaults=defaults(execution_backend_default="none"))

            filesystem = BackendFactory(RuntimeConfiguration({"CODEX_HOME": ""})).create(team_config, agent(toolsets=()))
            shell_composite = BackendFactory(RuntimeConfiguration({"EXECUTION_BACKEND": "local", "CODEX_HOME": ""})).create(
                team(
                    working_directory=tmp,
                    load_cwd=tmp,
                    team_defaults=defaults(
                        execution_backend_env="EXECUTION_BACKEND",
                        execution_backend_default="none",
                    )
                ),
                agent(toolsets=("shell",)),
            )

        self.assertEqual(type(filesystem).__name__, "FilesystemBackend")
        self.assertEqual(type(shell_composite).__name__, "CompositeBackend")

    def test_execution_backend_can_come_from_process_environment(self) -> None:
        with tempfile.TemporaryDirectory() as tmp, patch.dict(os.environ, {"EXECUTION_BACKEND": "local"}, clear=True):
            created = BackendFactory().create(
                team(working_directory=tmp, team_defaults=defaults(execution_backend_env="EXECUTION_BACKEND")),
                agent(toolsets=("shell",)),
            )

        self.assertEqual(type(created).__name__, "CompositeBackend")

    def test_skill_sources_are_mounted_as_virtual_filtered_routes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            launch_cwd = Path(tmp) / "repo"
            skills_dir = launch_cwd / ".agents" / "skills"
            (skills_dir / "allowed").mkdir(parents=True)
            (skills_dir / "allowed" / "SKILL.md").write_text("allowed", encoding="utf-8")
            (skills_dir / "hidden").mkdir()
            (skills_dir / "hidden" / "SKILL.md").write_text("hidden", encoding="utf-8")
            team_config = team(
                working_directory=launch_cwd,
                load_cwd=launch_cwd,
                agents={"entry": agent("entry", entrypoint=True, skills={"only": ["allowed"]})},
            )

            backend = BackendFactory(RuntimeConfiguration({"CODEX_HOME": ""})).create(
                team_config,
                team_config.agents["entry"],
            )

            listed = backend.ls("/skills/entry/project")
            read = backend.read("/skills/entry/project/allowed/SKILL.md")

            self.assertEqual([entry["path"] for entry in listed.entries], ["/skills/entry/project/allowed/"])
            self.assertIn("allowed", read.file_data["content"])


class CheckpointerFactoryTests(unittest.TestCase):
    def test_creates_memory_and_closes_optional_connections(self) -> None:
        handle = CheckpointerFactory().create(team(team_defaults=defaults(checkpointer_default="memory")))
        no_connection = CheckpointerHandle("checkpointer")

        no_connection.close()

        self.assertEqual(type(handle.checkpointer).__name__, "InMemorySaver")
        self.assertIsNone(handle.connection)

    def test_creates_sqlite_checkpointer_from_relative_and_absolute_paths(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            launch_cwd = Path(tmp) / "launcher"
            working = launch_cwd / "workspace"
            working.mkdir(parents=True)
            relative_handle = CheckpointerFactory(
                RuntimeConfiguration({"SQLITE_PATH": "state/checkpoints.sqlite"})
            ).create(
                team(
                    working_directory="workspace",
                    load_cwd=launch_cwd,
                    team_defaults=defaults(
                        checkpointer_default="sqlite",
                        sqlite_path_env="SQLITE_PATH",
                    )
                )
            )
            absolute_path = launch_cwd / "absolute.sqlite"
            absolute_handle = CheckpointerFactory().create(
                team(
                    working_directory="workspace",
                    load_cwd=launch_cwd,
                    team_defaults=defaults(
                        checkpointer_default="sqlite",
                        sqlite_path_default=str(absolute_path),
                    )
                )
            )

            self.assertTrue((launch_cwd / "state" / "checkpoints.sqlite").exists())
            self.assertFalse((working / "state" / "checkpoints.sqlite").exists())
            self.assertTrue(absolute_path.exists())
            self.assertEqual(type(relative_handle.checkpointer).__name__, "AsyncSqliteSaver")
            self.assertIsNotNone(relative_handle.async_runner)

            relative_handle.close()
            absolute_handle.close()

    def test_sqlite_checkpointer_start_failure_closes_runner_and_connection(self) -> None:
        class FailingAsyncRunner:
            def __init__(self) -> None:
                self.closed = False
                runners.append(self)

            def start_sqlite(self, _path: Path) -> object:
                raise RuntimeError("sqlite setup failed")

            def close(self) -> None:
                self.closed = True

        runners: list[FailingAsyncRunner] = []
        with tempfile.TemporaryDirectory() as tmp:
            sqlite_path = Path(tmp) / "checkpoints.sqlite"
            with patch("src.team_instanciator.factories.checkpointer_factory.AsyncCheckpointerLoop", FailingAsyncRunner):
                with self.assertRaisesRegex(RuntimeError, "sqlite setup failed"):
                    CheckpointerFactory().create(
                        team(
                            team_defaults=defaults(
                                checkpointer_default="sqlite",
                                sqlite_path_default=str(sqlite_path),
                            )
                        )
                    )

            self.assertTrue(runners[0].closed)

    def test_backend_and_sqlite_path_can_come_from_process_environment(self) -> None:
        with tempfile.TemporaryDirectory() as tmp, patch.dict(os.environ, {"CHECKPOINTER_BACKEND": "sqlite", "SQLITE_PATH": "env.sqlite"}, clear=True):
            launch_cwd = Path(tmp) / "launcher"
            working = launch_cwd / "workspace"
            working.mkdir(parents=True)
            handle = CheckpointerFactory().create(
                team(
                    working_directory="workspace",
                    load_cwd=launch_cwd,
                    team_defaults=defaults(
                        checkpointer_env="CHECKPOINTER_BACKEND",
                        sqlite_path_env="SQLITE_PATH",
                    )
                )
            )

            self.assertTrue((launch_cwd / "env.sqlite").exists())
            self.assertFalse((working / "env.sqlite").exists())
            handle.close()

    def test_unsupported_and_unimplemented_backends_raise(self) -> None:
        with self.assertRaisesRegex(TeamInstanciatorError, "Postgres"):
            CheckpointerFactory().create(team(team_defaults=defaults(checkpointer_default="postgres")))

        with self.assertRaisesRegex(TeamInstanciatorError, "Unsupported"):
            CheckpointerFactory().create(team(team_defaults=defaults(checkpointer_default="custom")))


if __name__ == "__main__":
    unittest.main()
