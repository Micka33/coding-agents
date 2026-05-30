from __future__ import annotations

import os
import sqlite3
from pathlib import Path

from langgraph.checkpoint.memory import MemorySaver
from langgraph.checkpoint.sqlite import SqliteSaver

from src.team_loader.team_definition import TeamDefinition

from .checkpointer_handle import CheckpointerHandle
from .root_dir_resolver import RootDirResolver
from .runtime_configuration import RuntimeConfiguration
from .team_instanciator_error import TeamInstanciatorError


class CheckpointerFactory:
    def __init__(self, configuration: RuntimeConfiguration | None = None) -> None:
        self._configuration = configuration or RuntimeConfiguration()
        self._root_dir_resolver = RootDirResolver()

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
            if os.environ.get(env):
                return os.environ[env]
        return team.defaults.checkpointer.default or "memory"

    def _sqlite_handle(self, team: TeamDefinition) -> CheckpointerHandle:
        raw_path = self._sqlite_path(team)
        path = Path(raw_path)
        if not path.is_absolute():
            path = self._root_dir_resolver.resolve(team) / path
        path.parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(path, check_same_thread=False)
        return CheckpointerHandle(SqliteSaver(connection), connection)

    def _sqlite_path(self, team: TeamDefinition) -> str:
        env = team.defaults.checkpointer.sqlite_path_env
        if env:
            configured = self._configuration.get(env)
            if configured:
                return str(configured)
            if os.environ.get(env):
                return os.environ[env]
        return team.defaults.checkpointer.sqlite_path_default or ".team-instanciator/checkpoints.sqlite"
