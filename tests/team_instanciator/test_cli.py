from __future__ import annotations

import io
import json
import runpy
import sys
import unittest
import warnings
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from src.team_instanciator.interfaces import cli as cli_module
from src.team_instanciator.interfaces import cli_support


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


class FakeConversation:
    def __init__(self) -> None:
        self.calls = []

    def append_human_message(self, message, wait=True):
        self.calls.append((message, wait))
        return SimpleNamespace(
            event=SimpleNamespace(seq=1, to_dict=lambda: {"seq": 1, "author_id": "human", "content": message}),
            deliveries=(
                SimpleNamespace(
                    status="failed",
                    to_dict=lambda: {
                        "agent_id": "agent",
                        "status": "failed",
                        "error": "boom",
                    },
                ),
            ),
            failures=(
                SimpleNamespace(
                    status="failed",
                    to_dict=lambda: {
                        "agent_id": "agent",
                        "status": "failed",
                        "error": "boom",
                    },
                ),
            ),
        )

    def state(self):
        return {"events": [{"seq": 1, "author_id": "human", "content": "Hi"}]}


class FakeConversationTeam(FakeInstantiatedTeam):
    def __init__(self) -> None:
        super().__init__()
        self.conversation = FakeConversation()

    def conversation_for(self, thread_id):
        return self.conversation


class FakeLauncher:
    calls = []

    def launch(self, **kwargs):
        self.__class__.calls.append(kwargs)


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
        FakeLauncher.calls = []

    def test_main_prints_json_summary_and_passes_variables_and_config(self) -> None:
        output = io.StringIO()

        with (
            patch("src.team_instanciator.interfaces.cli.TeamInstanciator", FakeTeamInstanciator),
            patch("src.team_instanciator.interfaces.cli.DotEnvLoader.load", return_value={"ENV_VALUE": "from-file"}),
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

        with patch("src.team_instanciator.interfaces.cli.TeamInstanciator", FakeTeamInstanciator), redirect_stdout(output):
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

    def test_cli_support_builds_config_variables_from_env_file_args_and_keys(self) -> None:
        args = SimpleNamespace(
            no_env_file=False,
            env_file=".env.custom",
            config=["runtime=value", "ignored"],
            openai_api_key="openai",
            tavily_api_key="tavily",
        )

        with patch("src.team_instanciator.interfaces.cli_support.DotEnvLoader.load", return_value={"ENV": "value"}) as load:
            values = cli_support.build_config_variables(args)

        load.assert_called_once_with(Path(".env.custom"))
        self.assertEqual(
            values,
            {
                "ENV": "value",
                "runtime": "value",
                "openai_api_key": "openai",
                "tavily_api_key": "tavily",
            },
        )

    def test_conversation_message_prints_json_failures_and_skips_direct_graph(self) -> None:
        conversation_team = FakeConversationTeam()
        FakeTeamInstanciator.instance = conversation_team
        output = io.StringIO()

        with patch("src.team_instanciator.interfaces.cli.TeamInstanciator", FakeTeamInstanciator), redirect_stdout(output):
            cli_module.TeamInstanciatorCli().main(["team.yaml", "--no-env-file", "--message", "Hi", "--json"])

        payload = json.loads(output.getvalue())
        self.assertEqual(conversation_team.conversation.calls, [("Hi", True)])
        self.assertEqual(conversation_team.invoke_calls, [])
        self.assertEqual(payload["failures"][0]["error"], "boom")

    def test_conversation_plain_message_prints_failures_to_stderr(self) -> None:
        conversation_team = FakeConversationTeam()
        FakeTeamInstanciator.instance = conversation_team
        output = io.StringIO()
        errors = io.StringIO()

        with (
            patch("src.team_instanciator.interfaces.cli.TeamInstanciator", FakeTeamInstanciator),
            redirect_stdout(output),
            redirect_stderr(errors),
        ):
            cli_module.TeamInstanciatorCli().main(["team.yaml", "--no-env-file", "--message", "Hi"])

        self.assertIn("human: Hi", output.getvalue())
        self.assertIn("warning: delivery to agent", errors.getvalue())

    def test_conversation_team_without_message_auto_launches_webapp(self) -> None:
        conversation_team = FakeConversationTeam()
        FakeTeamInstanciator.instance = conversation_team

        with (
            patch("src.team_instanciator.interfaces.cli.TeamInstanciator", FakeTeamInstanciator),
            patch("src.webapp.server.ConversationWebAppLauncher", return_value=FakeLauncher()),
        ):
            cli_module.TeamInstanciatorCli().main(
                ["team.yaml", "--no-env-file", "--thread-id", "thread-1", "--webapp-port", "9999"]
            )

        self.assertEqual(FakeLauncher.calls[0]["conversation_id"], "thread-1")
        self.assertEqual(FakeLauncher.calls[0]["port"], 9999)

    def test_webapp_subcommand_delegates_to_webapp_main(self) -> None:
        with patch("src.webapp.server.main", return_value=7) as webapp_main:
            exit_code = cli_module.TeamInstanciatorCli().main(["webapp", "team.yaml"])

        self.assertEqual(exit_code, 7)
        webapp_main.assert_called_once_with(["team.yaml"])

    def test_module_main_guard_runs(self) -> None:
        output = io.StringIO()

        with warnings.catch_warnings():
            warnings.simplefilter("ignore", RuntimeWarning)
            with patch.object(sys, "argv", ["cli.py", "--help"]), redirect_stdout(output), self.assertRaises(SystemExit) as raised:
                runpy.run_module("src.team_instanciator.interfaces.cli", run_name="__main__")

        self.assertEqual(raised.exception.code, 0)
        self.assertIn("Instantiate a team graph", output.getvalue())


if __name__ == "__main__":
    unittest.main()
