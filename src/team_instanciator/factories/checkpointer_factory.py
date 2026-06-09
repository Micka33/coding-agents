from __future__ import annotations

import os
import sqlite3
from pathlib import Path

from langgraph.checkpoint.memory import MemorySaver

from src.team_loader.models.team_definition import TeamDefinition
from src.team_loader.resolvers.working_directory_resolver import WorkingDirectoryResolver

from src.team_instanciator.runtime.async_checkpointer_loop import AsyncCheckpointerLoop
from src.team_instanciator.runtime.checkpointer_handle import CheckpointerHandle
from src.team_instanciator.configuration.runtime_configuration import RuntimeConfiguration
from src.team_instanciator.errors.team_instanciator_error import TeamInstanciatorError


class CheckpointerFactory:
    def __init__(self, configuration: RuntimeConfiguration | None = None) -> None:
        self._configuration = configuration or RuntimeConfiguration()
        self._working_directory_resolver = WorkingDirectoryResolver()

    def create(self, team: TeamDefinition) -> CheckpointerHandle:
        backend = self._backend_name(team)
        if backend == "memory":
            return CheckpointerHandle(MemorySaver())
        if backend == "sqlite":
            return self._sqlite_handle(team)
        if backend == "postgres":
            raise TeamInstanciatorError("Postgres checkpointers are not implemented by this self-contained instantiator.")
        raise TeamInstanciatorError(f"Unsupported checkpointer backend: {backend}")

    def _backend_name(self, team: TeamDefinition) -> str:
        env = team.defaults.checkpointer.env
        if env:
            configured = self._configuration.get(env)
            if configured:
                return str(configured)
        return team.defaults.checkpointer.default or "memory"

    def _sqlite_handle(self, team: TeamDefinition) -> CheckpointerHandle:
        raw_path = self._sqlite_path(team)
        path = Path(raw_path)
        if not path.is_absolute():
            path = self._working_directory_resolver.resolve_launch_cwd(team) / path
        path.parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(path, check_same_thread=False)
        try:
            connection.execute("PRAGMA busy_timeout = 5000")
            async_runner = AsyncCheckpointerLoop()
            try:
                checkpointer = async_runner.start_sqlite(path)
            except Exception:
                async_runner.close()
                raise
            return CheckpointerHandle(checkpointer, connection, async_runner)
        except Exception:
            connection.close()
            raise

    def _sqlite_path(self, team: TeamDefinition) -> str:
        env = team.defaults.checkpointer.sqlite_path_env
        if env:
            configured = self._configuration.get(env)
            if configured:
                return str(configured)
        return team.defaults.checkpointer.sqlite_path_default or ".team-instanciator/checkpoints.sqlite"
