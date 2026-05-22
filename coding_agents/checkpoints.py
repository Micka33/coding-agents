"""Checkpointer factory for agent conversation persistence."""

from __future__ import annotations

from contextlib import AbstractContextManager
from dataclasses import dataclass
from typing import Any

from langgraph.checkpoint.memory import MemorySaver
from langgraph.checkpoint.postgres import PostgresSaver
from langgraph.checkpoint.sqlite import SqliteSaver

from coding_agents.config import AgentTeamConfig


@dataclass
class CheckpointerHandle:
    """A checkpointer plus any context manager needed to keep it alive."""

    checkpointer: Any
    backend: str
    location: str
    _context: AbstractContextManager[Any] | None = None

    def close(self) -> None:
        """Close the underlying checkpointer resources."""

        if self._context is None:
            return
        self._context.__exit__(None, None, None)
        self._context = None


def create_checkpointer_handle(config: AgentTeamConfig) -> CheckpointerHandle:
    """Create the configured checkpointer handle."""

    backend = config.resolved_checkpointer_backend()

    if backend == "memory":
        return CheckpointerHandle(
            checkpointer=MemorySaver(),
            backend="memory",
            location="process memory",
        )

    if backend == "sqlite":
        path = config.resolved_sqlite_checkpoint_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        context = SqliteSaver.from_conn_string(str(path))
        checkpointer = context.__enter__()
        checkpointer.setup()
        return CheckpointerHandle(
            checkpointer=checkpointer,
            backend="sqlite",
            location=str(path),
            _context=context,
        )

    postgres_url = config.resolved_postgres_checkpoint_url()
    if not postgres_url:
        raise ValueError(
            "Postgres checkpointing requires CODING_AGENTS_POSTGRES_URL or DATABASE_URL."
        )

    context = PostgresSaver.from_conn_string(postgres_url)
    checkpointer = context.__enter__()
    checkpointer.setup()
    return CheckpointerHandle(
        checkpointer=checkpointer,
        backend="postgres",
        location="configured Postgres database",
        _context=context,
    )
