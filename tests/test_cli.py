from __future__ import annotations

import importlib.metadata
import io
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from coding_agents.cli import main


class CliSmokeTests(unittest.TestCase):
    def test_console_script_points_to_cli_main(self) -> None:
        console_scripts = importlib.metadata.entry_points(group="console_scripts")
        matching = [entry_point for entry_point in console_scripts if entry_point.name == "coding-agents"]

        self.assertEqual(len(matching), 1)
        self.assertEqual(matching[0].value, "coding_agents.cli:main")

    def test_cli_reaches_interactive_prompt_in_auto_mode_without_readiness_approval(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            fake_agent = SimpleNamespace(
                checkpointer_handle=SimpleNamespace(backend="memory", location="test"),
                get_state=Mock(return_value=SimpleNamespace(values={"messages": []})),
                close=Mock(),
            )
            stdout = io.StringIO()
            stderr = io.StringIO()

            with (
                patch("coding_agents.cli.create_development_team_agent", return_value=fake_agent) as create_agent,
                patch("builtins.input", side_effect=EOFError) as prompt,
                patch("sys.stdout", stdout),
                patch("sys.stderr", stderr),
            ):
                status = main(
                    [
                        "--root",
                        str(root),
                        "--checkpointer",
                        "memory",
                        "--execution",
                        "none",
                    ]
                )

            self.assertEqual(status, 0)
            self.assertEqual(stderr.getvalue(), "")
            output = stdout.getvalue()
            self.assertIn("Development Agent Team", output)
            self.assertIn("Mode: auto (current: shaping)", output)
            self.assertIn("Checkpointer: memory (test)", output)
            self.assertIn("Execution: none", output)
            self.assertTrue((root / "docs/agent-workflow/readiness-gate.yaml").is_file())
            prompt.assert_called_once_with("\nuser> ")
            fake_agent.get_state.assert_called_once_with(
                {"configurable": {"thread_id": "development-agent-team"}}
            )
            fake_agent.close.assert_called_once()

            config = create_agent.call_args.args[0]
            self.assertEqual(config.mode, "shaping")
            self.assertTrue(config.auto_transition)
            self.assertEqual(len(config.manager_tools), 1)
            self.assertEqual(config.checkpointer_backend, "memory")
            self.assertEqual(config.execution_backend, "none")
            self.assertEqual(Path(config.root_dir), root)

    def test_prompt_mode_approves_gate_and_switches_to_implementation_after_handoff(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            created_agents: list[SimpleNamespace] = []

            def fake_create_agent(config: object) -> SimpleNamespace:
                agent = SimpleNamespace(
                    config=config,
                    checkpointer_handle=SimpleNamespace(backend="memory", location="test"),
                    get_state=Mock(return_value=SimpleNamespace(values={"messages": []})),
                    close=Mock(),
                )

                def invoke(payload: dict[str, object], *, config: dict[str, object]) -> dict[str, object]:
                    if agent.config.mode == "shaping":
                        tool = agent.config.manager_tools[0]
                        tool.invoke(
                            {
                                "task": "Add auto mode",
                                "scope": "coding_agents/cli.py and tests/",
                                "acceptance_criteria": "Auto mode switches after handoff.",
                                "validation_plan": "Run unit tests.",
                                "risks": "Mode transition bugs.",
                                "notes": "Bounded CLI task.",
                            }
                        )
                        return {"messages": [SimpleNamespace(content="Ready to implement.")]}
                    return {"messages": [SimpleNamespace(content="Implemented.")]}

                agent.invoke = Mock(side_effect=invoke)
                created_agents.append(agent)
                return agent

            stdout = io.StringIO()
            stderr = io.StringIO()

            with (
                patch("coding_agents.cli.create_development_team_agent", side_effect=fake_create_agent) as create_agent,
                patch("builtins.input", side_effect=AssertionError("input should not be called")) as prompt,
                patch("sys.stdout", stdout),
                patch("sys.stderr", stderr),
            ):
                status = main(
                    [
                        "--root",
                        str(root),
                        "--checkpointer",
                        "memory",
                        "--execution",
                        "none",
                        "--prompt",
                        "build auto mode",
                    ]
                )

            self.assertEqual(status, 0)
            self.assertEqual(stderr.getvalue(), "")
            output = stdout.getvalue()
            self.assertIn("Auto mode: readiness gate approved", output)
            self.assertIn("Auto mode: switched to implementation.", output)
            self.assertIn("manager> Implemented.", output)
            self.assertEqual(create_agent.call_count, 2)
            self.assertEqual(created_agents[0].config.mode, "shaping")
            self.assertEqual(created_agents[1].config.mode, "implementation")
            self.assertEqual(created_agents[1].config.manager_tools, ())
            self.assertTrue((root / "docs/agent-workflow/readiness-gate.yaml").read_text(encoding="utf-8").startswith("# Machine-readable"))
            self.assertIn("approved_by: \"auto-mode\"", (root / "docs/agent-workflow/readiness-gate.yaml").read_text(encoding="utf-8"))
            prompt.assert_not_called()
            created_agents[0].close.assert_called_once()
            created_agents[1].close.assert_called_once()


if __name__ == "__main__":
    unittest.main()
