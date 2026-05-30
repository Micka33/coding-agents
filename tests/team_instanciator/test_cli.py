from __future__ import annotations

import io
import json
import runpy
import sys
import unittest
import warnings
from contextlib import redirect_stdout
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from src.team_instanciator import cli as cli_module


class CliTeam(SimpleNamespace):
    def entrypoint(self):
        return SimpleNamespace(id="entry")


class FakeInstantiatedTeam:
    def __init__(self) -> None:
        self.closed = False
        self.team = CliTeam(
            id="product",
            agents={"worker": object(), "entry": object()},
            relations=(object(), object()),
        )
        self.invoke_calls = []

    def invoke(self, input, config=None):
        self.invoke_calls.append((input, config))
        return {
            "messages": [
                {"role": "user", "content": "hello"},
                SimpleNamespace(type="ai", name="entry", content="answer", tool_calls=[{"id": "call"}]),
            ]
        }

    def close(self) -> None:
        self.closed = True


class FakeTeamInstanciator:
    calls = []
    instance = FakeInstantiatedTeam()

    def __init__(self, config_variables=None) -> None:
        self.config_variables = config_variables

    def instantiate(self, team_file, variables):
        self.__class__.calls.append((self.config_variables, team_file, variables))
        return self.__class__.instance


class CliTests(unittest.TestCase):
    def setUp(self) -> None:
        FakeTeamInstanciator.calls = []
        FakeTeamInstanciator.instance = FakeInstantiatedTeam()

    def test_main_prints_json_summary_and_passes_variables_and_config(self) -> None:
        output = io.StringIO()

        with (
            patch("src.team_instanciator.cli.TeamInstanciator", FakeTeamInstanciator),
            patch("src.team_instanciator.cli.DotEnvLoader.load", return_value={"ENV_VALUE": "from-file"}),
            redirect_stdout(output),
        ):
            exit_code = cli_module.main(
                [
                    "team.yaml",
                    "--env-file",
                    ".env",
                    "--var",
                    "topic=ai",
                    "--var",
                    "ignored",
                    "--config",
                    "runtime=value",
                    "--openai-api-key",
                    "openai",
                    "--tavily-api-key",
                    "tavily",
                    "--json",
                ]
            )

        self.assertEqual(exit_code, 0)
        self.assertTrue(FakeTeamInstanciator.instance.closed)
        self.assertEqual(
            FakeTeamInstanciator.calls[0],
            (
                {
                    "ENV_VALUE": "from-file",
                    "runtime": "value",
                    "openai_api_key": "openai",
                    "tavily_api_key": "tavily",
                },
                "team.yaml",
                {"topic": "ai"},
            ),
        )
        self.assertEqual(json.loads(output.getvalue())["agents"], ["entry", "worker"])

    def test_message_invocation_prints_json_and_uses_thread_id(self) -> None:
        output = io.StringIO()

        with patch("src.team_instanciator.cli.TeamInstanciator", FakeTeamInstanciator), redirect_stdout(output):
            cli_module.TeamInstanciatorCli().main(["team.yaml", "--no-env-file", "--message", "Hi", "--thread-id", "thread-1", "--json"])

        self.assertEqual(
            FakeTeamInstanciator.instance.invoke_calls[0],
            (
                {"messages": [{"role": "user", "content": "Hi"}]},
                {"configurable": {"thread_id": "thread-1"}},
            ),
        )
        messages = json.loads(output.getvalue())["messages"]
        self.assertEqual(messages[1]["name"], "entry")
        self.assertEqual(messages[1]["tool_calls"], [{"id": "call"}])

    def test_plain_summary_and_plain_result_output(self) -> None:
        instantiated = FakeInstantiatedTeam()
        output = io.StringIO()
        cli = cli_module.TeamInstanciatorCli()

        with redirect_stdout(output):
            cli._print_summary(instantiated, as_json=False)
            cli._print_result(instantiated, "Hi", thread_id=None, as_json=False)

        text = output.getvalue()
        self.assertIn("Team: product", text)
        self.assertIn("Entrypoint: entry", text)
        self.assertIn("Relations: 2", text)
        self.assertIn("ai (entry): answer", text)
        self.assertEqual(instantiated.invoke_calls[0][1], {"configurable": {"thread_id": "product"}})

    def test_message_normalization_handles_non_dict_results_dicts_and_objects(self) -> None:
        cli = cli_module.TeamInstanciatorCli()

        self.assertEqual(cli._messages("not-a-dict"), [])
        self.assertEqual(cli._message({"role": "tool", "name": "tool", "content": None}), {"role": "tool", "name": "tool", "content": "", "tool_calls": []})

    def test_module_main_guard_runs(self) -> None:
        output = io.StringIO()

        with warnings.catch_warnings():
            warnings.simplefilter("ignore", RuntimeWarning)
            with patch.object(sys, "argv", ["cli.py", "--help"]), redirect_stdout(output), self.assertRaises(SystemExit) as raised:
                runpy.run_module("src.team_instanciator.cli", run_name="__main__")

        self.assertEqual(raised.exception.code, 0)
        self.assertIn("Instantiate a team graph", output.getvalue())


if __name__ == "__main__":
    unittest.main()
