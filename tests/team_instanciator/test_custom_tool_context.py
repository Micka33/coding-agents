from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import patch

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage
from langchain_core.tools import StructuredTool
from langgraph.graph.message import REMOVE_ALL_MESSAGES

from src.team_instanciator.checkpointer_handle import CheckpointerHandle
from src.team_instanciator.custom_tool_context import ConversationHistory, CustomToolContext, EnvView
from src.team_instanciator.custom_tool_factory import CustomToolFactory
from src.team_instanciator.runtime_configuration import RuntimeConfiguration
from src.team_instanciator.toolset_resolver import ToolsetResolver
from src.team_loader.custom_tool_definition import CustomToolDefinition
from src.team_loader.tool_reference import ToolReference


LAST_CONTEXT: CustomToolContext | None = None
LAST_ARGS: dict[str, Any] | None = None


def context_probe_tools(context: CustomToolContext, args: dict[str, Any]) -> list[StructuredTool]:
    global LAST_CONTEXT, LAST_ARGS
    LAST_CONTEXT = context
    LAST_ARGS = args

    def context_probe(value: str) -> str:
        """Return the configured prefix and input value."""

        return f"{args['prefix']}{value}"

    return [StructuredTool.from_function(context_probe, name="context_probe")]


class FakeCheckpointer:
    def __init__(self) -> None:
        self.list_calls: list[tuple[dict[str, Any], int]] = []
        self.get_tuple_calls: list[dict[str, Any]] = []

    def list(self, config: dict[str, Any], *, limit: int):
        self.list_calls.append((config, limit))
        return ["checkpoint"]

    def get_tuple(self, config: dict[str, Any]) -> str:
        self.get_tuple_calls.append(config)
        return "latest"


class CustomToolContextTests(unittest.TestCase):
    def tearDown(self) -> None:
        global LAST_CONTEXT, LAST_ARGS
        LAST_CONTEXT = None
        LAST_ARGS = None

    def test_factory_receives_standard_context_and_user_args(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            context = CustomToolContext(
                root_dir=root,
                env=EnvView(RuntimeConfiguration({"CUSTOM_ENV": "configured"})),
                runtime_config=RuntimeConfiguration({"CUSTOM_ENV": "configured"}),
                agent_config=SimpleNamespace(id="agent"),
                team_config=SimpleNamespace(id="team"),
                history=ConversationHistory("checkpointer"),
                checkpointer="checkpointer",
            )
            definition = CustomToolDefinition(
                id="probe",
                factory=f"{__name__}:context_probe_tools",
                args={"prefix": "ok:"},
                exposes=("context_probe",),
            )

            tools = CustomToolFactory().create(definition, context)

        self.assertEqual([tool.name for tool in tools], ["context_probe"])
        self.assertIs(LAST_CONTEXT, context)
        self.assertEqual(LAST_ARGS, {"prefix": "ok:"})
        self.assertEqual(tools[0].invoke({"value": "value"}), "ok:value")

    def test_toolset_resolver_passes_agent_team_config_and_checkpointer(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            checkpointer = FakeCheckpointer()
            team = SimpleNamespace(
                defaults=SimpleNamespace(root_dir=str(root)),
                custom_tools={
                    "probe": CustomToolDefinition(
                        id="probe",
                        factory=f"{__name__}:context_probe_tools",
                        args={"prefix": "team:"},
                        exposes=("context_probe",),
                    )
                },
                toolsets={"custom": SimpleNamespace(tools=(ToolReference(custom="probe"),))},
            )
            agent = SimpleNamespace(id="agent", toolsets=("custom",))

            tools = ToolsetResolver(
                RuntimeConfiguration({"CUSTOM_ENV": "configured"}),
                CheckpointerHandle(checkpointer),
            ).resolve_for_langchain(team, agent)

        self.assertEqual([tool.name for tool in tools], ["context_probe"])
        self.assertIsNotNone(LAST_CONTEXT)
        assert LAST_CONTEXT is not None
        self.assertEqual(LAST_CONTEXT.root_dir, root)
        self.assertIs(LAST_CONTEXT.agent_config, agent)
        self.assertIs(LAST_CONTEXT.team_config, team)
        self.assertIs(LAST_CONTEXT.checkpointer, checkpointer)
        self.assertEqual(LAST_CONTEXT.env["CUSTOM_ENV"], "configured")

    def test_env_view_reads_runtime_configuration_and_process_environment(self) -> None:
        with patch.dict(os.environ, {"PROCESS_ENV": "process"}, clear=False):
            env = EnvView(RuntimeConfiguration({"RUNTIME_ENV": "runtime"}))

            self.assertEqual(env["RUNTIME_ENV"], "runtime")
            self.assertEqual(env["PROCESS_ENV"], "process")
            self.assertEqual(env.as_dict(["RUNTIME_ENV", "PROCESS_ENV", "MISSING"]), {"RUNTIME_ENV": "runtime", "PROCESS_ENV": "process"})

    def test_env_view_require_mapping_iteration_and_missing_key(self) -> None:
        with patch.dict(os.environ, {"PROCESS_ENV": "process"}, clear=True):
            env = EnvView(RuntimeConfiguration({"RUNTIME_ENV": "runtime"}))

            self.assertEqual(env.get("MISSING", "fallback"), "fallback")
            self.assertEqual(env.require("RUNTIME_ENV"), "runtime")
            self.assertEqual(env.as_dict(), {"PROCESS_ENV": "process", "RUNTIME_ENV": "runtime"})
            self.assertEqual(set(iter(env)), {"PROCESS_ENV", "RUNTIME_ENV"})
            self.assertEqual(len(env), 2)
            with self.assertRaisesRegex(KeyError, "Missing required"):
                env.require("MISSING")
            with self.assertRaises(KeyError):
                _ = env["MISSING"]

    def test_conversation_history_counts_messages_and_usage(self) -> None:
        messages = [
            HumanMessage(content="hello"),
            AIMessage(
                content="calling",
                tool_calls=[{"id": "call-1", "name": "lookup", "args": {}}],
                usage_metadata={"input_tokens": 10, "output_tokens": 4, "total_tokens": 14},
            ),
            ToolMessage(content="result", tool_call_id="call-1"),
            AIMessage(
                content="done",
                response_metadata={"token_usage": {"prompt_tokens": 2, "completion_tokens": 3, "total_tokens": 5}},
            ),
            SystemMessage(content="note"),
        ]

        counts = ConversationHistory(None).count_messages(messages)

        self.assertEqual(counts["total"], 5)
        self.assertEqual(counts["human"], 1)
        self.assertEqual(counts["ai"], 2)
        self.assertEqual(counts["system"], 1)
        self.assertEqual(counts["tool"], 1)
        self.assertEqual(counts["tool_call_requests"], 1)
        self.assertEqual(counts["tool_results"], 1)
        self.assertEqual(counts["input_tokens"], 12)
        self.assertEqual(counts["output_tokens"], 7)
        self.assertEqual(counts["total_tokens"], 19)

    def test_conversation_history_reads_checkpoints_from_current_runtime_config(self) -> None:
        checkpointer = FakeCheckpointer()
        runtime = SimpleNamespace(
            config={"configurable": {"thread_id": "thread-1"}},
            state={"messages": []},
            tool_call_id="call-1",
        )
        history = ConversationHistory(checkpointer)

        self.assertEqual(history.thread_id(runtime), "thread-1")
        self.assertEqual(history.latest_checkpoint(runtime), "latest")
        self.assertEqual(history.checkpoints(runtime, limit=3), ["checkpoint"])
        self.assertEqual(checkpointer.get_tuple_calls, [{"configurable": {"thread_id": "thread-1"}}])
        self.assertEqual(checkpointer.list_calls, [({"configurable": {"thread_id": "thread-1"}}, 3)])

    def test_conversation_history_handles_missing_runtime_state_and_other_message_shapes(self) -> None:
        history = ConversationHistory(None)
        runtime = SimpleNamespace(config={}, state=SimpleNamespace(messages=("one", "two"), single="value"), tool_call_id=None)

        self.assertIsNone(history.checkpointer)
        self.assertEqual(history.current_state(runtime), runtime.state)
        self.assertEqual(history.current_messages(SimpleNamespace(state={}, config={}, tool_call_id=None)), [])
        self.assertEqual(history.current_messages(runtime), ["one", "two"])
        self.assertEqual(history.current_messages(runtime, key="single"), ["value"])
        self.assertIsNone(history.latest_checkpoint(runtime))
        self.assertEqual(history.checkpoints(runtime, limit=0), [])
        with self.assertRaisesRegex(ValueError, "thread_id"):
            history.thread_id(runtime)
        with self.assertRaisesRegex(ValueError, "tool_call_id"):
            history.replace_messages_command(runtime, [])

        counts = history.count_messages(
            [
                {"role": "alien", "tool_calls": [SimpleNamespace(id="call-1")], "usage_metadata": {"prompt_tokens": 1}},
                {"role": "assistant", "additional_kwargs": {"tool_calls": [{"id": "call-2"}]}},
            ]
        )
        self.assertEqual(counts["other"], 1)
        self.assertEqual(counts["tool_call_requests"], 2)
        self.assertEqual(counts["input_tokens"], 1)

    def test_compact_messages_command_keeps_triggering_tool_call_and_visible_result(self) -> None:
        triggering_message = AIMessage(
            content="compact",
            tool_calls=[{"id": "call-1", "name": "compact_context", "args": {}}],
        )
        runtime = SimpleNamespace(
            config={"configurable": {"thread_id": "thread-1"}},
            state={"messages": [HumanMessage(content="old"), triggering_message]},
            tool_call_id="call-1",
        )

        command = ConversationHistory(None).compact_messages_command(
            runtime,
            summary="Earlier context summarized.",
            keep_last=0,
            visible_result="Visible compact result.",
        )

        messages_update = command.update["messages"]
        self.assertEqual(messages_update[0].id, REMOVE_ALL_MESSAGES)
        self.assertIsInstance(messages_update[1], SystemMessage)
        self.assertIs(messages_update[2], triggering_message)
        self.assertIsInstance(messages_update[3], ToolMessage)
        self.assertEqual(messages_update[3].tool_call_id, "call-1")
        self.assertEqual(messages_update[3].content, "Visible compact result.")

    def test_compact_messages_command_keeps_tool_result_pairs_at_tail_boundary(self) -> None:
        tool_request = AIMessage(
            content="lookup",
            tool_calls=[{"id": "lookup-1", "name": "lookup", "args": {}}],
        )
        tool_result = ToolMessage(content="lookup result", tool_call_id="lookup-1")
        triggering_message = AIMessage(
            content="compact",
            tool_calls=[{"id": "compact-1", "name": "compact_context", "args": {}}],
        )
        runtime = SimpleNamespace(
            config={"configurable": {"thread_id": "thread-1"}},
            state={"messages": [HumanMessage(content="old"), tool_request, tool_result, triggering_message]},
            tool_call_id="compact-1",
        )

        command = ConversationHistory(None).compact_messages_command(
            runtime,
            summary="Earlier context summarized.",
            keep_last=2,
        )

        messages_update = command.update["messages"]
        self.assertIn(tool_request, messages_update)
        self.assertIn(tool_result, messages_update)
        self.assertIn(triggering_message, messages_update)

    def test_custom_tool_context_alias_properties(self) -> None:
        context = CustomToolContext(
            root_dir=Path.cwd(),
            env=EnvView(RuntimeConfiguration()),
            runtime_config=RuntimeConfiguration(),
            agent_config=SimpleNamespace(id="agent"),
            team_config=SimpleNamespace(id="team"),
            history=ConversationHistory(None),
        )

        self.assertIs(context.agent, context.agent_config)
        self.assertIs(context.team, context.team_config)


if __name__ == "__main__":
    unittest.main()
