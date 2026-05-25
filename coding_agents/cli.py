"""Minimal interactive CLI for the development-agent team."""

from __future__ import annotations

import argparse
import os
import sys
import traceback
from pathlib import Path
from typing import Iterable

from coding_agents.artifacts import ensure_agent_workflow_files
from coding_agents.config import (
    CHECKPOINTER_BACKEND_ENV,
    DEFAULT_ARTIFACTS_DIR,
    DEFAULT_CHECKPOINTER_BACKEND,
    DEFAULT_MODEL,
    DEFAULT_SCOUT_REASONING_EFFORT,
    DEFAULT_SQLITE_CHECKPOINT_PATH,
    DEFAULT_THREAD_ID,
    EXECUTION_BACKEND_ENV,
    POSTGRES_CHECKPOINT_URL_ENV,
    REASONING_EFFORT_ENV,
    SCOUT_MODEL_ENV,
    SCOUT_REASONING_EFFORT_ENV,
    SQLITE_CHECKPOINT_PATH_ENV,
    AgentMode,
    AgentTeamConfig,
    CheckpointerBackend,
    ExecutionBackend,
    default_execution_backend,
)
from coding_agents.env import load_dotenv_file
from coding_agents.messages import conversation_transcript, last_message_text
from coding_agents.paths import validate_artifacts_dir
from coding_agents.readiness import ReadinessGateError
from coding_agents.redaction import redact_secrets
from coding_agents.team import create_development_team_agent


def main(argv: Iterable[str] | None = None) -> int:
    """Run the interactive CLI."""

    args = _parse_args(argv)
    model_for_error = args.model or os.environ.get("CODING_AGENTS_MODEL", DEFAULT_MODEL)
    try:
        artifacts_dir = validate_artifacts_dir(args.artifacts_dir)
        load_dotenv_file(args.root / ".env")
        model = args.model or os.environ.get("CODING_AGENTS_MODEL", DEFAULT_MODEL)
        model_for_error = model
        reasoning_effort = args.reasoning_effort or os.environ.get(REASONING_EFFORT_ENV)
        scout_model = args.scout_model or os.environ.get(SCOUT_MODEL_ENV) or model
        scout_reasoning_effort = (
            args.scout_reasoning_effort
            or os.environ.get(SCOUT_REASONING_EFFORT_ENV)
            or DEFAULT_SCOUT_REASONING_EFFORT
        )
        checkpointer_backend = (
            args.checkpointer
            or os.environ.get(CHECKPOINTER_BACKEND_ENV)
            or DEFAULT_CHECKPOINTER_BACKEND
        )
        execution_backend = (
            args.execution
            or os.environ.get(EXECUTION_BACKEND_ENV)
            or default_execution_backend(args.mode)
        )
        sqlite_checkpoint_path = (
            args.sqlite_checkpoint_path
            or os.environ.get(SQLITE_CHECKPOINT_PATH_ENV)
            or DEFAULT_SQLITE_CHECKPOINT_PATH
        )
        postgres_checkpoint_url = (
            args.postgres_checkpoint_url
            or os.environ.get(POSTGRES_CHECKPOINT_URL_ENV)
            or os.environ.get("DATABASE_URL")
        )

        if args.init_artifacts:
            created = ensure_agent_workflow_files(args.root, artifacts_dir)
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
            artifacts_dir=artifacts_dir,
            reasoning_effort=reasoning_effort,
            scout_model=scout_model,
            scout_reasoning_effort=scout_reasoning_effort,
            checkpointer_backend=checkpointer_backend,
            sqlite_checkpoint_path=sqlite_checkpoint_path,
            postgres_checkpoint_url=postgres_checkpoint_url,
            execution_backend=execution_backend,
            implementation_write_paths=tuple(args.write_paths),
            debug=args.debug,
            initialize_artifacts=args.init_artifacts,
        )

        agent = create_development_team_agent(config)
    except Exception as exc:  # pragma: no cover - provider/startup errors vary
        _print_startup_error(exc, model_for_error)
        return 1

    print("Development Agent Team")
    print(f"Mode: {args.mode}")
    print(f"Model: {model}")
    if reasoning_effort:
        print(f"Reasoning effort: {reasoning_effort}")
    if scout_reasoning_effort:
        print(f"Scout: {scout_model} ({scout_reasoning_effort})")
    print(f"Checkpointer: {agent.checkpointer_handle.backend} ({agent.checkpointer_handle.location})")
    print(f"Execution: {execution_backend}")
    print(f"Thread: {args.thread_id}")
    print("Type /exit to quit, /help for commands.")
    _print_restored_conversation(agent, args.thread_id)

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
                _print_help(artifacts_dir)
                continue

            try:
                result = agent.invoke(
                    {"messages": [{"role": "user", "content": user_input}]},
                    config={"configurable": {"thread_id": args.thread_id}},
                )
            except Exception as exc:  # pragma: no cover - model/runtime errors vary
                if args.debug:
                    print(redact_secrets(traceback.format_exc()), file=sys.stderr, end="")
                print(f"\nError: {redact_secrets(exc)}", file=sys.stderr)
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
        "--scout-model",
        default=None,
        help=f"Scout model string or {SCOUT_MODEL_ENV} value.",
    )
    parser.add_argument(
        "--scout-reasoning-effort",
        default=None,
        help=f"Scout reasoning effort or {SCOUT_REASONING_EFFORT_ENV} value.",
    )
    parser.add_argument(
        "--mode",
        choices=["shaping", "implementation"],
        default="shaping",
        type=_agent_mode,
        help="Workflow mode for this run. Implementation mode requires an approved readiness gate.",
    )
    parser.add_argument(
        "--write-path",
        dest="write_paths",
        action="append",
        default=[],
        help=(
            "Repository-relative implementation write restriction path. Repeat for multiple paths. "
            "Omit to allow repo-wide implementation writes except protected files. "
            "Directories must end with '/' to include descendants."
        ),
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
        "--execution",
        choices=["none", "local"],
        default=None,
        type=_execution_backend,
        help=(
            "Command execution backend. Shaping and implementation default to 'local'. "
            "Use 'none' to disable command execution because "
            "local commands execute on this machine."
        ),
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
        type=_artifacts_dir,
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


def _execution_backend(value: str) -> ExecutionBackend:
    if value not in {"none", "local"}:
        raise argparse.ArgumentTypeError("execution must be none or local")
    return value  # type: ignore[return-value]


def _artifacts_dir(value: str) -> str:
    try:
        return validate_artifacts_dir(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(str(exc)) from exc


def _print_help(artifacts_dir: str) -> None:
    print(
        f"""
Commands:
  /help   Show this help
  /exit   Quit the CLI

Workflow:
  - shaping mode is the default
  - implementation mode requires readiness-gate.yaml approved for full_implementation
  - implementation writes are repo-wide by default except protected files
  - use --write-path to restrict implementation writes
  - shaping and implementation use local command execution by default; use --execution none to disable it
  - workflow artifacts live in {artifacts_dir}
""".strip()
    )


def _print_restored_conversation(agent: object, thread_id: str) -> None:
    try:
        snapshot = agent.get_state(  # type: ignore[attr-defined]
            {"configurable": {"thread_id": thread_id}}
        )
    except Exception as exc:  # pragma: no cover - checkpoint backends vary
        print(f"\nCould not restore conversation history: {redact_secrets(exc)}", file=sys.stderr)
        return

    values = getattr(snapshot, "values", {}) or {}
    messages = values.get("messages") or []
    transcript = conversation_transcript(messages)
    if not transcript:
        return

    print("\nRestored conversation:")
    for role, text in transcript:
        print(f"\n{role}> {text}")


def _print_startup_error(exc: Exception, model: str) -> None:
    print(f"Could not start the development-agent team: {redact_secrets(exc)}", file=sys.stderr)
    if isinstance(exc, ReadinessGateError):
        print(
            "Hint: implementation mode requires docs/agent-workflow/readiness-gate.yaml "
            "with approved: true, approval_scope: full_implementation, and non-empty "
            "approved_by/approved_date. After approval, implementation has repo-wide "
            "write access except protected files; use --write-path only to restrict it.",
            file=sys.stderr,
        )
        return
    if model.startswith("openai:"):
        print(
            "Hint: set OPENAI_API_KEY or choose another model with --model or CODING_AGENTS_MODEL.",
            file=sys.stderr,
        )


if __name__ == "__main__":
    raise SystemExit(main())
