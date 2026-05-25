from __future__ import annotations

import io
import tempfile
import unittest
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, call, patch

from deepagents.middleware.filesystem import _check_fs_permission

from coding_agents.cli import _parse_args, _print_restored_conversation, _print_startup_error, main
from coding_agents.config import AgentTeamConfig
from coding_agents.readiness import ReadinessGateError
from coding_agents.resident_agents import create_resident_agent_team
from coding_agents.team import _resolve_model_value, create_development_team_agent


APPROVED_GATE = """approved: true
approval_scope: full_implementation
approved_by: Engineering Manager
approved_date: 2026-05-24
notes: Approved for team construction tests.
"""


@contextmanager
def patched_team_construction():
    checkpointer_handle = SimpleNamespace(
        checkpointer=None,
        backend="memory",
        location="test",
        close=Mock(),
    )
    resident_team = SimpleNamespace(manager_tools=Mock(return_value=[]))

    with (
        patch("coding_agents.team._resolve_model", return_value="model") as resolve_model,
        patch("coding_agents.team._resolve_scout_model", return_value="scout-model") as resolve_scout_model,
        patch("coding_agents.team.default_tools", return_value=[]) as default_tools,
        patch("coding_agents.team.disable_default_general_purpose_subagent") as disable_general_purpose,
        patch("coding_agents.team.create_checkpointer_handle", return_value=checkpointer_handle) as create_checkpointer_handle,
        patch("coding_agents.team.create_resident_agent_team", return_value=resident_team) as create_resident_agent_team,
        patch("coding_agents.team.create_scout_subagent", return_value={"name": "scout"}) as create_scout_subagent,
        patch("coding_agents.team.implementation_subagents", return_value=[{"name": "developer"}]) as implementation_subagents,
        patch("coding_agents.team.SafeFilesystemBackend", return_value="backend") as filesystem_backend,
        patch(
            "coding_agents.team.SafeLocalShellBackend",
            return_value="local-backend",
        ) as local_shell_backend,
        patch("coding_agents.team.create_deep_agent", return_value="graph") as create_deep_agent,
    ):
        yield {
            "resolve_model": resolve_model,
            "resolve_scout_model": resolve_scout_model,
            "default_tools": default_tools,
            "disable_general_purpose": disable_general_purpose,
            "create_checkpointer_handle": create_checkpointer_handle,
            "create_resident_agent_team": create_resident_agent_team,
            "create_scout_subagent": create_scout_subagent,
            "implementation_subagents": implementation_subagents,
            "filesystem_backend": filesystem_backend,
            "local_shell_backend": local_shell_backend,
            "create_deep_agent": create_deep_agent,
            "checkpointer_handle": checkpointer_handle,
        }


class TeamGovernanceTests(unittest.TestCase):
    def test_shaping_constructs_without_readiness_and_registers_only_scout(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            config = AgentTeamConfig(
                root_dir=Path(tmp),
                mode="shaping",
                model="test:model",
                scout_model="test:scout",
                checkpointer_backend="memory",
                initialize_artifacts=False,
            )

            with patched_team_construction() as patched:
                agent = create_development_team_agent(config)

            self.assertEqual(agent.graph, "graph")
            patched["implementation_subagents"].assert_not_called()
            kwargs = patched["create_deep_agent"].call_args.kwargs
            self.assertEqual(kwargs["backend"], "backend")
            self.assertEqual(kwargs["subagents"], [{"name": "scout"}])
            patched["disable_general_purpose"].assert_has_calls([call("test:model"), call("model")])
            self.assertEqual(
                _check_fs_permission(kwargs["permissions"], "write", "/coding_agents/config.py"),
                "deny",
            )

    def test_invalid_artifacts_dir_fails_before_artifact_initialization(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            config = AgentTeamConfig(
                root_dir=Path(tmp),
                mode="shaping",
                artifacts_dir=".",
                checkpointer_backend="memory",
                initialize_artifacts=True,
            )

            with patch("coding_agents.team.ensure_agent_workflow_files") as ensure_artifacts:
                with self.assertRaises(ValueError):
                    create_development_team_agent(config)

            ensure_artifacts.assert_not_called()

    def test_symlinked_workflow_artifact_fails_before_agent_construction(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            artifact_dir = root / "docs/agent-workflow"
            artifact_dir.mkdir(parents=True)
            target = root / "coding_agents/team.py"
            target.parent.mkdir()
            target.write_text("protected\n", encoding="utf-8")
            try:
                (artifact_dir / "product-brief.md").symlink_to(target)
            except OSError as exc:  # pragma: no cover - platform dependent
                self.skipTest(f"symlinks unavailable: {exc}")
            config = AgentTeamConfig(
                root_dir=root,
                mode="shaping",
                checkpointer_backend="memory",
                initialize_artifacts=False,
            )

            with patch("coding_agents.team.create_deep_agent") as create_deep_agent:
                with self.assertRaisesRegex(ValueError, "symlink"):
                    create_development_team_agent(config)

            create_deep_agent.assert_not_called()

    def test_implementation_missing_readiness_fails_before_model_or_subagents(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            config = AgentTeamConfig(
                root_dir=Path(tmp),
                mode="implementation",
                checkpointer_backend="memory",
                initialize_artifacts=False,
            )

            with (
                patch("coding_agents.team._resolve_model") as resolve_model,
                patch("coding_agents.team.create_deep_agent") as create_deep_agent,
            ):
                with self.assertRaises(ReadinessGateError):
                    create_development_team_agent(config)

            resolve_model.assert_not_called()
            create_deep_agent.assert_not_called()

    def test_implementation_registers_subagents_only_after_approved_readiness(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            gate_dir = root / "docs/agent-workflow"
            gate_dir.mkdir(parents=True)
            (gate_dir / "readiness-gate.yaml").write_text(APPROVED_GATE, encoding="utf-8")
            config = AgentTeamConfig(
                root_dir=root,
                mode="implementation",
                model="test:model",
                scout_model="test:scout",
                checkpointer_backend="memory",
                implementation_write_paths=("coding_agents/config.py",),
                initialize_artifacts=False,
            )

            with patched_team_construction() as patched:
                create_development_team_agent(config)

            patched["implementation_subagents"].assert_called_once_with([])
            patched["disable_general_purpose"].assert_has_calls([call("test:model"), call("model")])
            kwargs = patched["create_deep_agent"].call_args.kwargs
            self.assertEqual(kwargs["subagents"], [{"name": "scout"}, {"name": "developer"}])
            self.assertEqual(
                _check_fs_permission(kwargs["permissions"], "write", "/coding_agents/config.py"),
                "allow",
            )
            self.assertEqual(
                _check_fs_permission(kwargs["permissions"], "write", "/README.md"),
                "deny",
            )
            self.assertEqual(kwargs["backend"], "backend")

    def test_implementation_local_execution_uses_local_shell_backend(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            gate_dir = root / "docs/agent-workflow"
            gate_dir.mkdir(parents=True)
            (gate_dir / "readiness-gate.yaml").write_text(APPROVED_GATE, encoding="utf-8")
            config = AgentTeamConfig(
                root_dir=root,
                mode="implementation",
                model="test:model",
                scout_model="test:scout",
                checkpointer_backend="memory",
                execution_backend="local",
                implementation_write_paths=("coding_agents/config.py",),
                initialize_artifacts=False,
            )

            with patched_team_construction() as patched:
                create_development_team_agent(config)

            patched["filesystem_backend"].assert_not_called()
            patched["local_shell_backend"].assert_called_once_with(
                root_dir=root.resolve(),
                virtual_mode=True,
            )
            kwargs = patched["create_deep_agent"].call_args.kwargs
            self.assertEqual(kwargs["backend"], "local-backend")

    def test_shaping_local_execution_uses_local_shell_backend_without_implementation_subagents(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            config = AgentTeamConfig(
                root_dir=root,
                mode="shaping",
                model="test:model",
                scout_model="test:scout",
                checkpointer_backend="memory",
                execution_backend="local",
                initialize_artifacts=True,
            )

            with patched_team_construction() as patched:
                create_development_team_agent(config)

            patched["implementation_subagents"].assert_not_called()
            patched["filesystem_backend"].assert_not_called()
            patched["local_shell_backend"].assert_called_once_with(
                root_dir=root.resolve(),
                virtual_mode=True,
            )
            kwargs = patched["create_deep_agent"].call_args.kwargs
            self.assertEqual(kwargs["backend"], "local-backend")
            self.assertEqual(kwargs["subagents"], [{"name": "scout"}])
            self.assertEqual(
                _check_fs_permission(kwargs["permissions"], "write", "/coding_agents/config.py"),
                "deny",
            )
            self.assertEqual(
                _check_fs_permission(kwargs["permissions"], "write", "/docs/agent-workflow/readiness-gate.md"),
                "allow",
            )
            self.assertEqual(
                _check_fs_permission(kwargs["permissions"], "write", "/docs/agent-workflow/readiness-gate.yaml"),
                "deny",
            )

    def test_resident_agents_disable_default_general_purpose_subagent(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            with (
                patch("coding_agents.resident_agents.disable_default_general_purpose_subagent") as disable_general_purpose,
                patch("coding_agents.resident_agents.SafeFilesystemBackend", return_value="backend"),
                patch("coding_agents.resident_agents.create_deep_agent", side_effect=["product", "architect"]) as create_deep_agent,
            ):
                resident_team = create_resident_agent_team(
                    model="test:model",
                    root_dir=Path(tmp),
                    artifacts_dir="docs/agent-workflow",
                    parent_thread_id="thread",
                    tools=[],
                    memory=None,
                    checkpointer=None,
                )

        disable_general_purpose.assert_called_once_with("test:model")
        self.assertEqual(create_deep_agent.call_count, 2)
        self.assertEqual(resident_team.product_agent, "product")
        self.assertEqual(resident_team.architect_agent, "architect")

    def test_openai_reasoning_effort_requests_responses_summary_blocks(self) -> None:
        with patch("coding_agents.team.init_chat_model", return_value="model") as init_chat_model:
            model = _resolve_model_value(model="openai:gpt-5.4", reasoning_effort="medium")

        self.assertEqual(model, "model")
        init_chat_model.assert_called_once_with(
            model="openai:gpt-5.4",
            reasoning={"effort": "medium", "summary": "auto"},
            use_responses_api=True,
            output_version="responses/v1",
        )

    def test_non_openai_reasoning_effort_keeps_provider_neutral_parameter(self) -> None:
        with patch("coding_agents.team.init_chat_model", return_value="model") as init_chat_model:
            model = _resolve_model_value(model="anthropic:claude-sonnet-4-5", reasoning_effort="high")

        self.assertEqual(model, "model")
        init_chat_model.assert_called_once_with(
            model="anthropic:claude-sonnet-4-5",
            reasoning_effort="high",
        )

    def test_cli_rejects_unsafe_artifacts_dir(self) -> None:
        with self.assertRaises(SystemExit):
            _parse_args(["--artifacts-dir", "."])

    def test_cli_accepts_repeated_implementation_write_paths(self) -> None:
        args = _parse_args(
            [
                "--mode",
                "implementation",
                "--write-path",
                "coding_agents/config.py",
                "--write-path",
                "tests/",
            ]
        )

        self.assertEqual(args.write_paths, ["coding_agents/config.py", "tests/"])

    def test_cli_accepts_execution_backend(self) -> None:
        args = _parse_args(["--execution", "local"])

        self.assertEqual(args.execution, "local")

    def test_cli_readiness_startup_error_includes_gate_and_write_scope_hint(self) -> None:
        stderr = io.StringIO()
        with patch("sys.stderr", stderr):
            _print_startup_error(ReadinessGateError("blocked"), "test:model")

        output = stderr.getvalue()
        self.assertIn("readiness-gate.yaml", output)
        self.assertIn("full_implementation", output)
        self.assertIn("--write-path", output)

    def test_cli_startup_error_redacts_secret_patterns(self) -> None:
        stderr = io.StringIO()
        with patch("sys.stderr", stderr):
            _print_startup_error(
                RuntimeError("postgres://user:pass@host/db password=hunter2 token=abc123"),
                "test:model",
            )

        output = stderr.getvalue()
        self.assertIn("postgres://***:***@host/db", output)
        self.assertNotIn("user:pass", output)
        for secret in ("hunter2", "abc123"):
            self.assertNotIn(secret, output)
        self.assertIn("password=<redacted>", output)
        self.assertIn("token=<redacted>", output)

    def test_cli_dotenv_startup_failure_is_redacted_before_agent_construction(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            stderr = io.StringIO()
            with (
                patch("sys.stderr", stderr),
                patch(
                    "coding_agents.cli.load_dotenv_file",
                    side_effect=RuntimeError("api_key=sk-dotenv postgres://user:pass@host/db"),
                ),
                patch("coding_agents.cli.create_development_team_agent") as create_agent,
            ):
                status = main(["--root", tmp, "--no-init-artifacts", "--checkpointer", "memory"])

        output = stderr.getvalue()
        self.assertEqual(status, 1)
        create_agent.assert_not_called()
        self.assertNotIn("sk-dotenv", output)
        self.assertNotIn("user:pass", output)
        self.assertIn("api_key=<redacted>", output)
        self.assertIn("postgres://***:***@host/db", output)

    def test_cli_artifact_startup_failure_is_redacted_before_agent_construction(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            stderr = io.StringIO()
            with (
                patch("sys.stderr", stderr),
                patch("coding_agents.cli.load_dotenv_file"),
                patch(
                    "coding_agents.cli.ensure_agent_workflow_files",
                    side_effect=RuntimeError("token=artifact-secret postgres://user:pass@host/db"),
                ),
                patch("coding_agents.cli.create_development_team_agent") as create_agent,
            ):
                status = main(["--root", tmp, "--init-only", "--checkpointer", "memory"])

        output = stderr.getvalue()
        self.assertEqual(status, 1)
        create_agent.assert_not_called()
        self.assertNotIn("artifact-secret", output)
        self.assertNotIn("user:pass", output)
        self.assertIn("token=<redacted>", output)
        self.assertIn("postgres://***:***@host/db", output)

    def test_cli_restore_error_redacts_secret_patterns(self) -> None:
        agent = SimpleNamespace(
            get_state=Mock(side_effect=RuntimeError("api_key=sk-restore secret=hidden"))
        )
        stderr = io.StringIO()

        with patch("sys.stderr", stderr):
            _print_restored_conversation(agent, "thread")

        output = stderr.getvalue()
        self.assertNotIn("sk-restore", output)
        self.assertNotIn("hidden", output)
        self.assertIn("api_key=<redacted>", output)
        self.assertIn("secret=<redacted>", output)


if __name__ == "__main__":
    unittest.main()
