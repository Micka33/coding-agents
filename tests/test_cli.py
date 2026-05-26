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

    def test_cli_reaches_interactive_prompt_in_shaping_mode_without_readiness_approval(self) -> None:
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
            self.assertIn("Mode: shaping", output)
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
            self.assertEqual(config.checkpointer_backend, "memory")
            self.assertEqual(config.execution_backend, "none")
            self.assertEqual(Path(config.root_dir), root)


if __name__ == "__main__":
    unittest.main()
