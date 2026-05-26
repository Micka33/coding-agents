"""Minimal interactive CLI for the development-agent team."""

from __future__ import annotations

import argparse
import os
import sys
import traceback
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

from langchain_core.tools import BaseTool, StructuredTool

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
    ReadinessApprovalPolicy,
    WorkflowMode,
    default_execution_backend,
)
from coding_agents.env import load_dotenv_file
from coding_agents.messages import conversation_transcript, last_message_text
from coding_agents.paths import validate_artifacts_dir
from coding_agents.readiness import (
    ReadinessGateError,
    approve_readiness_gate,
    assert_readiness_approved,
)
from coding_agents.redaction import redact_secrets
from coding_agents.team import create_development_team_agent


@dataclass
class ImplementationHandoff:
    """Structured handoff from auto-shaping to implementation mode."""

    task: str
    scope: str
    acceptance_criteria: str
    validation_plan: str
    risks: str = ""
    notes: str = ""

    def missing_fields(self) -> list[str]:
        """Return required fields that are empty."""

        required = {
            "task": self.task,
            "scope": self.scope,
            "acceptance_criteria": self.acceptance_criteria,
            "validation_plan": self.validation_plan,
        }
        return [name for name, value in required.items() if not value.strip()]

    def gate_notes(self) -> str:
        """Return compact notes for the readiness gate."""

        return (
            "Approved automatically from auto-mode readiness handoff. "
            f"Task: {self.task.strip()} Scope: {self.scope.strip()}"
        )

    def implementation_prompt(self) -> str:
        """Return the prompt used to resume in implementation mode."""

        return f"""Auto-mode implementation handoff.

Implement this bounded task now. Keep the work inside the stated scope unless a
blocking reason requires escalation back to the engineering manager.

Task:
{self.task.strip()}

Scope:
{self.scope.strip()}

Acceptance criteria:
{self.acceptance_criteria.strip()}

Validation plan:
{self.validation_plan.strip()}

Risks:
{self.risks.strip() or "None stated."}

Notes:
{self.notes.strip() or "None."}
"""


class AutoModeController:
    """Runtime state for CLI-managed auto mode."""

    def __init__(self, readiness_approval: ReadinessApprovalPolicy) -> None:
        self.readiness_approval = readiness_approval
        self.pending_handoff: ImplementationHandoff | None = None

    def tools(self) -> tuple[BaseTool, ...]:
        """Return manager-only tools for auto-mode handoff."""

        def request_implementation_handoff(
            task: str,
            scope: str,
            acceptance_criteria: str,
            validation_plan: str,
            risks: str = "",
            notes: str = "",
        ) -> str:
            """Request the runtime to switch from shaping to implementation mode."""

            handoff = ImplementationHandoff(
                task=task.strip(),
                scope=scope.strip(),
                acceptance_criteria=acceptance_criteria.strip(),
                validation_plan=validation_plan.strip(),
                risks=risks.strip(),
                notes=notes.strip(),
            )
            missing = handoff.missing_fields()
            if missing:
                return (
                    "Implementation handoff rejected. Missing required fields: "
                    f"{', '.join(missing)}."
                )

            self.pending_handoff = handoff
            return (
                "Implementation handoff accepted by the CLI runtime. Finish your "
                "current response concisely; the runtime will handle readiness and "
                "restart in implementation mode when allowed."
            )

        return (
            StructuredTool.from_function(
                func=request_implementation_handoff,
                name="request_implementation_handoff",
                description=(
                    "Ask the trusted CLI runtime to move an auto-mode session from "
                    "shaping to implementation. Use only when the task is bounded "
                    "and has scope, acceptance criteria, validation plan, risks, "
                    "and notes."
                ),
            ),
        )

    def consume_handoff(self) -> ImplementationHandoff | None:
        """Return and clear the pending implementation handoff."""

        handoff = self.pending_handoff
        self.pending_handoff = None
        return handoff


def main(argv: Iterable[str] | None = None) -> int:
    """Run the interactive CLI."""

    args = _parse_args(argv)
    model_for_error = args.model or os.environ.get("CODING_AGENTS_MODEL", DEFAULT_MODEL)
    active_mode = _initial_agent_mode(args.mode)
    auto_controller = (
        AutoModeController(args.readiness_approval) if args.mode == "auto" else None
    )
    try:
        artifacts_dir = validate_artifacts_dir(args.artifacts_dir)
        _load_environment_files(args.root, args.env_file)
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
            or default_execution_backend(active_mode)
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

        config = _agent_config(
            args,
            mode=active_mode,
            model=model,
            reasoning_effort=reasoning_effort,
            scout_model=scout_model,
            scout_reasoning_effort=scout_reasoning_effort,
            checkpointer_backend=checkpointer_backend,
            sqlite_checkpoint_path=sqlite_checkpoint_path,
            postgres_checkpoint_url=postgres_checkpoint_url,
            execution_backend=execution_backend,
            artifacts_dir=artifacts_dir,
            manager_tools=auto_controller.tools() if auto_controller else (),
            auto_transition=auto_controller is not None,
        )

        agent = create_development_team_agent(config)
    except Exception as exc:  # pragma: no cover - provider/startup errors vary
        _print_startup_error(exc, model_for_error)
        return 1

    print("Development Agent Team")
    print(f"Mode: {_mode_label(args.mode, active_mode)}")
    print(f"Model: {model}")
    if reasoning_effort:
        print(f"Reasoning effort: {reasoning_effort}")
    if scout_reasoning_effort:
        print(f"Scout: {scout_model} ({scout_reasoning_effort})")
    print(f"Checkpointer: {agent.checkpointer_handle.backend} ({agent.checkpointer_handle.location})")
    print(f"Execution: {execution_backend}")
    print(f"Thread: {args.thread_id}")
    if args.prompt is None:
        print("Type /exit to quit, /help for commands.")
    _print_restored_conversation(agent, args.thread_id)

    try:
        if args.prompt is not None:
            agent, active_mode = _run_user_turn(
                args,
                agent=agent,
                active_mode=active_mode,
                user_input=args.prompt,
                auto_controller=auto_controller,
                model=model,
                reasoning_effort=reasoning_effort,
                scout_model=scout_model,
                scout_reasoning_effort=scout_reasoning_effort,
                checkpointer_backend=checkpointer_backend,
                sqlite_checkpoint_path=sqlite_checkpoint_path,
                postgres_checkpoint_url=postgres_checkpoint_url,
                execution_backend=execution_backend,
                artifacts_dir=artifacts_dir,
            )
            return 0

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

            agent, active_mode = _run_user_turn(
                args,
                agent=agent,
                active_mode=active_mode,
                user_input=user_input,
                auto_controller=auto_controller,
                model=model,
                reasoning_effort=reasoning_effort,
                scout_model=scout_model,
                scout_reasoning_effort=scout_reasoning_effort,
                checkpointer_backend=checkpointer_backend,
                sqlite_checkpoint_path=sqlite_checkpoint_path,
                postgres_checkpoint_url=postgres_checkpoint_url,
                execution_backend=execution_backend,
                artifacts_dir=artifacts_dir,
            )
    finally:
        agent.close()


def _run_user_turn(
    args: argparse.Namespace,
    *,
    agent: object,
    active_mode: AgentMode,
    user_input: str,
    auto_controller: AutoModeController | None,
    model: str,
    reasoning_effort: str | None,
    scout_model: str,
    scout_reasoning_effort: str | None,
    checkpointer_backend: CheckpointerBackend,
    sqlite_checkpoint_path: str | Path,
    postgres_checkpoint_url: str | None,
    execution_backend: ExecutionBackend,
    artifacts_dir: str,
) -> tuple[object, AgentMode]:
    try:
        result = agent.invoke(  # type: ignore[attr-defined]
            {"messages": [{"role": "user", "content": user_input}]},
            config={"configurable": {"thread_id": args.thread_id}},
        )
    except Exception as exc:  # pragma: no cover - model/runtime errors vary
        if args.debug:
            print(redact_secrets(traceback.format_exc()), file=sys.stderr, end="")
        print(f"\nError: {redact_secrets(exc)}", file=sys.stderr)
        return agent, active_mode

    print(f"\nmanager> {last_message_text(result)}")
    if not auto_controller or active_mode != "shaping":
        return agent, active_mode

    handoff = auto_controller.consume_handoff()
    if not handoff:
        return agent, active_mode
    if not _ensure_auto_readiness(
        args,
        artifacts_dir=artifacts_dir,
        handoff=handoff,
        readiness_approval=auto_controller.readiness_approval,
    ):
        return agent, active_mode

    try:
        config = _agent_config(
            args,
            mode="implementation",
            model=model,
            reasoning_effort=reasoning_effort,
            scout_model=scout_model,
            scout_reasoning_effort=scout_reasoning_effort,
            checkpointer_backend=checkpointer_backend,
            sqlite_checkpoint_path=sqlite_checkpoint_path,
            postgres_checkpoint_url=postgres_checkpoint_url,
            execution_backend=execution_backend,
            artifacts_dir=artifacts_dir,
        )
        next_agent = create_development_team_agent(config)
        agent.close()  # type: ignore[attr-defined]
        agent = next_agent
        active_mode = "implementation"
        print("\nAuto mode: switched to implementation.")
        result = agent.invoke(  # type: ignore[attr-defined]
            {"messages": [{"role": "user", "content": handoff.implementation_prompt()}]},
            config={"configurable": {"thread_id": args.thread_id}},
        )
    except Exception as exc:  # pragma: no cover - model/runtime errors vary
        if args.debug:
            print(redact_secrets(traceback.format_exc()), file=sys.stderr, end="")
        print(f"\nError: {redact_secrets(exc)}", file=sys.stderr)
        return agent, active_mode

    print(f"\nmanager> {last_message_text(result)}")
    return agent, active_mode


def _load_environment_files(root_dir: Path, explicit_env_file: Path | None) -> None:
    """Load root and fallback .env files without overriding earlier values."""

    for env_file in _environment_file_candidates(root_dir, explicit_env_file):
        load_dotenv_file(env_file)


def _environment_file_candidates(
    root_dir: Path,
    explicit_env_file: Path | None,
) -> tuple[Path, ...]:
    """Return .env files to try in load order."""

    candidates = [Path(root_dir) / ".env"]
    if explicit_env_file is not None:
        candidates.append(explicit_env_file)
    else:
        candidates.extend(
            [
                Path.cwd() / ".env",
                Path(__file__).resolve().parent.parent / ".env",
            ]
        )
    return _dedupe_paths(candidates)


def _dedupe_paths(paths: list[Path]) -> tuple[Path, ...]:
    seen: set[Path] = set()
    deduped: list[Path] = []
    for path in paths:
        try:
            key = path.resolve()
        except OSError:
            key = path.absolute()
        if key in seen:
            continue
        seen.add(key)
        deduped.append(path)
    return tuple(deduped)


def _agent_config(
    args: argparse.Namespace,
    *,
    mode: AgentMode,
    model: str,
    reasoning_effort: str | None,
    scout_model: str,
    scout_reasoning_effort: str | None,
    checkpointer_backend: CheckpointerBackend,
    sqlite_checkpoint_path: str | Path,
    postgres_checkpoint_url: str | None,
    execution_backend: ExecutionBackend,
    artifacts_dir: str,
    manager_tools: tuple[BaseTool, ...] = (),
    auto_transition: bool = False,
) -> AgentTeamConfig:
    return AgentTeamConfig(
        model=model,
        root_dir=args.root,
        mode=mode,
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
        manager_tools=manager_tools,
        auto_transition=auto_transition,
        debug=args.debug,
        initialize_artifacts=args.init_artifacts,
    )


def _initial_agent_mode(mode: WorkflowMode) -> AgentMode:
    if mode == "implementation":
        return "implementation"
    return "shaping"


def _mode_label(requested_mode: WorkflowMode, active_mode: AgentMode) -> str:
    if requested_mode == "auto":
        return f"auto (current: {active_mode})"
    return active_mode


def _ensure_auto_readiness(
    args: argparse.Namespace,
    *,
    artifacts_dir: str,
    handoff: ImplementationHandoff,
    readiness_approval: ReadinessApprovalPolicy,
) -> bool:
    try:
        assert_readiness_approved(args.root, artifacts_dir)
        return True
    except ReadinessGateError as exc:
        if readiness_approval == "manual":
            print(
                "\nAuto mode: implementation handoff is ready, but readiness approval "
                f"is manual. Gate remains blocked: {redact_secrets(exc)}",
                file=sys.stderr,
            )
            return False
        if readiness_approval == "confirm":
            answer = input("\nApprove readiness gate for implementation now? [y/N] ").strip()
            if answer.lower() not in {"y", "yes"}:
                print("\nAuto mode: readiness approval declined; staying in shaping.")
                return False

    try:
        status = approve_readiness_gate(
            args.root,
            artifacts_dir,
            approved_by="auto-mode",
            notes=handoff.gate_notes(),
        )
    except Exception as exc:  # pragma: no cover - filesystem/parser errors vary
        print(
            f"\nAuto mode: could not approve readiness gate: {redact_secrets(exc)}",
            file=sys.stderr,
        )
        return False

    print(f"\nAuto mode: readiness gate approved at {status.path}.")
    return True


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
        choices=["auto", "shaping", "implementation"],
        default="auto",
        type=_workflow_mode,
        help=(
            "Workflow mode for this run. Auto starts in shaping and can switch "
            "to implementation after a bounded handoff and readiness approval."
        ),
    )
    parser.add_argument(
        "--readiness-approval",
        choices=["auto", "confirm", "manual"],
        default="auto",
        type=_readiness_approval_policy,
        help=(
            "Readiness approval policy for --mode auto. 'auto' lets the trusted "
            "CLI runtime approve the gate after a bounded handoff; 'confirm' "
            "asks before writing; 'manual' never writes the gate."
        ),
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
        "--prompt",
        default=None,
        help=(
            "Run a single non-interactive user request, print the manager response, "
            "handle any auto-mode implementation handoff, and exit."
        ),
    )
    parser.add_argument(
        "--env-file",
        type=Path,
        default=None,
        help=(
            "Additional .env file to load after the root .env. Existing environment "
            "variables and root .env values take precedence."
        ),
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


def _workflow_mode(value: str) -> WorkflowMode:
    if value not in {"auto", "shaping", "implementation"}:
        raise argparse.ArgumentTypeError("mode must be auto, shaping, or implementation")
    return value  # type: ignore[return-value]


def _readiness_approval_policy(value: str) -> ReadinessApprovalPolicy:
    if value not in {"auto", "confirm", "manual"}:
        raise argparse.ArgumentTypeError("readiness approval must be auto, confirm, or manual")
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
  - auto mode is the default
  - use --prompt for a single non-interactive run
  - auto starts with shaping permissions and can switch to implementation after a bounded handoff
  - readiness approval in auto mode is controlled by --readiness-approval
  - implementation mode still requires readiness-gate.yaml approved for full_implementation
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
