"""Configuration for the development-agent team."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

from langchain_core.language_models.chat_models import BaseChatModel

from coding_agents.paths import validate_artifacts_dir


AgentMode = Literal["shaping", "implementation"]
CheckpointerBackend = Literal["memory", "sqlite", "postgres"]
ExecutionBackend = Literal["none", "local"]

DEFAULT_MODEL = "openai:gpt-5.4"
DEFAULT_THREAD_ID = "development-agent-team"
DEFAULT_ARTIFACTS_DIR = "docs/agent-workflow"
DEFAULT_CHECKPOINTER_BACKEND: CheckpointerBackend = "sqlite"
DEFAULT_EXECUTION_BACKEND: ExecutionBackend = "none"
DEFAULT_SQLITE_CHECKPOINT_PATH = ".coding-agents/checkpoints.sqlite"
DEFAULT_SCOUT_REASONING_EFFORT = "medium"
REASONING_EFFORT_ENV = "CODING_AGENTS_REASONING_EFFORT"
EXECUTION_BACKEND_ENV = "CODING_AGENTS_EXECUTION"
SCOUT_MODEL_ENV = "CODING_AGENTS_SCOUT_MODEL"
SCOUT_REASONING_EFFORT_ENV = "CODING_AGENTS_SCOUT_REASONING_EFFORT"
CHECKPOINTER_BACKEND_ENV = "CODING_AGENTS_CHECKPOINTER"
SQLITE_CHECKPOINT_PATH_ENV = "CODING_AGENTS_SQLITE_CHECKPOINT_PATH"
POSTGRES_CHECKPOINT_URL_ENV = "CODING_AGENTS_POSTGRES_URL"


@dataclass(frozen=True)
class AgentTeamConfig:
    """Runtime configuration for the development-agent team."""

    model: str | BaseChatModel | None = None
    root_dir: Path | str = Path(".")
    mode: AgentMode = "shaping"
    thread_id: str = DEFAULT_THREAD_ID
    artifacts_dir: str = DEFAULT_ARTIFACTS_DIR
    reasoning_effort: str | None = None
    scout_model: str | BaseChatModel | None = None
    scout_reasoning_effort: str | None = None
    checkpointer_backend: CheckpointerBackend | None = None
    sqlite_checkpoint_path: str | Path | None = None
    postgres_checkpoint_url: str | None = None
    execution_backend: ExecutionBackend | None = None
    skills: tuple[str, ...] = field(default_factory=tuple)
    memory: tuple[str, ...] = field(default_factory=tuple)
    implementation_write_paths: tuple[str, ...] = field(default_factory=tuple)
    debug: bool = False
    initialize_artifacts: bool = True

    def resolved_model(self) -> str | BaseChatModel:
        """Return the configured model or the environment/default model."""

        if self.model is not None:
            return self.model
        return os.environ.get("CODING_AGENTS_MODEL", DEFAULT_MODEL)

    def resolved_reasoning_effort(self) -> str | None:
        """Return the configured reasoning effort, if any."""

        if self.reasoning_effort is not None:
            return self.reasoning_effort
        return os.environ.get(REASONING_EFFORT_ENV)

    def resolved_scout_model(self) -> str | BaseChatModel:
        """Return the configured scout model or the main model."""

        if self.scout_model is not None:
            return self.scout_model
        configured = os.environ.get(SCOUT_MODEL_ENV)
        if configured:
            return configured
        return self.resolved_model()

    def resolved_scout_reasoning_effort(self) -> str | None:
        """Return the configured scout reasoning effort."""

        if self.scout_reasoning_effort is not None:
            return self.scout_reasoning_effort
        return os.environ.get(SCOUT_REASONING_EFFORT_ENV, DEFAULT_SCOUT_REASONING_EFFORT)

    def resolved_checkpointer_backend(self) -> CheckpointerBackend:
        """Return the configured checkpointer backend."""

        backend = self.checkpointer_backend or os.environ.get(CHECKPOINTER_BACKEND_ENV) or DEFAULT_CHECKPOINTER_BACKEND
        if backend not in {"memory", "sqlite", "postgres"}:
            raise ValueError("checkpointer backend must be one of: memory, sqlite, postgres")
        return backend

    def resolved_execution_backend(self) -> ExecutionBackend:
        """Return the configured command execution backend."""

        backend = (
            self.execution_backend
            or os.environ.get(EXECUTION_BACKEND_ENV)
            or DEFAULT_EXECUTION_BACKEND
        )
        if backend not in {"none", "local"}:
            raise ValueError("execution backend must be one of: none, local")
        return backend

    def resolved_sqlite_checkpoint_path(self) -> Path:
        """Return the configured SQLite checkpoint path."""

        raw_path = (
            self.sqlite_checkpoint_path
            or os.environ.get(SQLITE_CHECKPOINT_PATH_ENV)
            or DEFAULT_SQLITE_CHECKPOINT_PATH
        )
        path = Path(raw_path)
        if path.is_absolute():
            return path
        return self.resolved_root_dir() / path

    def resolved_postgres_checkpoint_url(self) -> str | None:
        """Return the configured Postgres checkpoint URL."""

        return (
            self.postgres_checkpoint_url
            or os.environ.get(POSTGRES_CHECKPOINT_URL_ENV)
            or os.environ.get("DATABASE_URL")
        )

    def resolved_root_dir(self) -> Path:
        """Return the root directory as an absolute path."""

        return Path(self.root_dir).resolve()

    def resolved_artifacts_dir(self) -> str:
        """Return the validated repository-relative artifact directory."""

        return validate_artifacts_dir(self.artifacts_dir)
