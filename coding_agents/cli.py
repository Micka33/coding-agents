"""Minimal interactive CLI for the development-agent team."""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path
from typing import Iterable

from coding_agents.artifacts import ensure_agent_workflow_files
from coding_agents.config import (
    CHECKPOINTER_BACKEND_ENV,
    DEFAULT_ARTIFACTS_DIR,
    DEFAULT_CHECKPOINTER_BACKEND,
    DEFAULT_MODEL,
    DEFAULT_SQLITE_CHECKPOINT_PATH,
    POSTGRES_CHECKPOINT_URL_ENV,
    DEFAULT_THREAD_ID,
    REASONING_EFFORT_ENV,
    SQLITE_CHECKPOINT_PATH_ENV,
    AgentMode,
    AgentTeamConfig,
    CheckpointerBackend,
)
from coding_agents.env import load_dotenv_file
from coding_agents.messages import last_message_text
from coding_agents.team import create_development_team_agent


def main(argv: Iterable[str] | None = None) -> int:
    """Run the interactive CLI."""

    args = _parse_args(argv)
    load_dotenv_file(args.root / ".env")
    model = args.model or os.environ.get("CODING_AGENTS_MODEL", DEFAULT_MODEL)
    reasoning_effort = args.reasoning_effort or os.environ.get(REASONING_EFFORT_ENV)
    checkpointer_backend = args.checkpointer or os.environ.get(CHECKPOINTER_BACKEND_ENV) or DEFAULT_CHECKPOINTER_BACKEND
    sqlite_checkpoint_path = args.sqlite_checkpoint_path or os.environ.get(SQLITE_CHECKPOINT_PATH_ENV) or DEFAULT_SQLITE_CHECKPOINT_PATH
    postgres_checkpoint_url = args.postgres_checkpoint_url or os.environ.get(POSTGRES_CHECKPOINT_URL_ENV) or os.environ.get("DATABASE_URL")

    if args.init_artifacts:
        created = ensure_agent_workflow_files(args.root, args.artifacts_dir)
        if created:
            print("Initialized workflow artifacts:")
            for path in created:
                print(f"- {path}")
        else:
            print("Workflow artifacts already exist.")
        if args.init_only:
            return 0

    config = AgentTeamConfig(
        model=model,
        root_dir=args.root,
        mode=args.mode,
        thread_id=args.thread_id,
        artifacts_dir=args.artifacts_dir,
        reasoning_effort=reasoning_effort,
        checkpointer_backend=checkpointer_backend,
        sqlite_checkpoint_path=sqlite_checkpoint_path,
        postgres_checkpoint_url=postgres_checkpoint_url,
        debug=args.debug,
        initialize_artifacts=args.init_artifacts,
    )

    try:
        agent = create_development_team_agent(config)
    except Exception as exc:  # pragma: no cover - provider errors vary
        _print_startup_error(exc, model)
        return 1

    print("Development Agent Team")
    print(f"Mode: {args.mode}")
    print(f"Model: {model}")
    if reasoning_effort:
        print(f"Reasoning effort: {reasoning_effort}")
    print(f"Checkpointer: {agent.checkpointer_handle.backend} ({agent.checkpointer_handle.location})")
    print(f"Thread: {args.thread_id}")
    print("Type /exit to quit, /help for commands.")

    try:
        while True:
            try:
                user_input = input("\nuser> ").strip()
            except (EOFError, KeyboardInterrupt):
                print()
                return 0

            if not user_input:
                continue
            if user_input in {"/exit", "/quit"}:
                return 0
            if user_input == "/help":
                _print_help(args.artifacts_dir)
                continue

            try:
                result = agent.invoke(
                    {"messages": [{"role": "user", "content": user_input}]},
                    config={"configurable": {"thread_id": args.thread_id}},
                )
            except Exception as exc:  # pragma: no cover - model/runtime errors vary
                print(f"\nError: {exc}", file=sys.stderr)
                continue

            print(f"\nmanager> {last_message_text(result)}")
    finally:
        agent.close()


def _parse_args(argv: Iterable[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run the development-agent team CLI.")
    parser.add_argument(
        "--model",
        default=None,
        help="LangChain model string or CODING_AGENTS_MODEL value.",
    )
    parser.add_argument(
        "--reasoning-effort",
        default=None,
        help=f"Model reasoning effort or {REASONING_EFFORT_ENV} value.",
    )
    parser.add_argument(
        "--mode",
        choices=["shaping", "implementation"],
        default="shaping",
        type=_agent_mode,
        help="Workflow mode for this run.",
    )
    parser.add_argument(
        "--thread-id",
        default=DEFAULT_THREAD_ID,
        help="Persistent thread id for the conversation.",
    )
    parser.add_argument(
        "--checkpointer",
        choices=["memory", "sqlite", "postgres"],
        default=None,
        type=_checkpointer_backend,
        help="Checkpoint backend for conversation memory.",
    )
    parser.add_argument(
        "--sqlite-checkpoint-path",
        default=None,
        help="SQLite checkpoint file path for the sqlite backend.",
    )
    parser.add_argument(
        "--postgres-checkpoint-url",
        default=None,
        help="Postgres connection URL for the postgres backend.",
    )
    parser.add_argument(
        "--root",
        type=Path,
        default=Path("."),
        help="Repository root used by the filesystem backend.",
    )
    parser.add_argument(
        "--artifacts-dir",
        default=DEFAULT_ARTIFACTS_DIR,
        help="Repository-relative folder for workflow artifacts.",
    )
    parser.add_argument(
        "--no-init-artifacts",
        dest="init_artifacts",
        action="store_false",
        help="Do not create missing workflow artifact files on startup.",
    )
    parser.add_argument(
        "--init-only",
        action="store_true",
        help="Create missing workflow artifact files and exit.",
    )
    parser.add_argument("--debug", action="store_true", help="Enable Deep Agents debug mode.")
    parser.set_defaults(init_artifacts=True)
    return parser.parse_args(list(argv) if argv is not None else None)


def _agent_mode(value: str) -> AgentMode:
    if value not in {"shaping", "implementation"}:
        raise argparse.ArgumentTypeError("mode must be shaping or implementation")
    return value  # type: ignore[return-value]


def _checkpointer_backend(value: str) -> CheckpointerBackend:
    if value not in {"memory", "sqlite", "postgres"}:
        raise argparse.ArgumentTypeError("checkpointer must be memory, sqlite, or postgres")
    return value  # type: ignore[return-value]


def _print_help(artifacts_dir: str) -> None:
    print(
        f"""
Commands:
  /help   Show this help
  /exit   Quit the CLI

Workflow:
  - shaping mode is the default
  - implementation mode should only be used after the readiness gate is approved
  - workflow artifacts live in {artifacts_dir}
""".strip()
    )


def _print_startup_error(exc: Exception, model: str) -> None:
    print(f"Could not start the development-agent team: {exc}", file=sys.stderr)
    if model.startswith("openai:"):
        print(
            "Hint: set OPENAI_API_KEY or choose another model with --model or CODING_AGENTS_MODEL.",
            file=sys.stderr,
        )


if __name__ == "__main__":
    raise SystemExit(main())
