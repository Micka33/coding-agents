from __future__ import annotations

import sqlite3
import threading
import time
import unittest
from types import SimpleNamespace

from src.team_instanciator.tools.relation_tool import RelationTool
from src.team_instanciator.factories.relation_tool_factory import RelationToolFactory
from src.team_instanciator.errors.team_instanciator_error import TeamInstanciatorError
from src.team_instanciator.runtime.thread_id_factory import ThreadIdFactory
from src.team_instanciator.runtime.tool_call_edge_recorder import ToolCallEdgeRecorder
from tests.support import FakeGraph, agent, relation, team


class Registry:
    def __init__(self, graph):
        self.graph_calls: list[str] = []
        self._graph = graph

    def graph(self, agent_id: str):
        self.graph_calls.append(agent_id)
        return self._graph


class RelationToolTests(unittest.TestCase):
    def test_run_invokes_target_graph_with_relation_thread_id_and_metadata(self) -> None:
        graph = FakeGraph({"messages": [SimpleNamespace(content="answer")]})
        registry = Registry(graph)
        relation_config = relation(source="entry", target="worker", tool_name="ask_worker")
        tool = RelationTool(
            relation_config,
            registry,
            parent_thread_id="fallback",
            thread_id_factory=ThreadIdFactory(),
            checkpoint_metadata={"team_id": "team", "agent_id": "worker"},
        )

        result = tool.run("question", SimpleNamespace(config={"configurable": {"thread_id": "root"}}, state={}, tool_call_id="call"))

        self.assertEqual(result, "answer")
        self.assertEqual(registry.graph_calls, ["worker"])
        self.assertEqual(graph.calls[0][0], {"messages": [{"role": "user", "content": "question"}]})
        self.assertEqual(graph.calls[0][1]["configurable"]["thread_id"], "root:relation:rel_worker:agent:worker")
        self.assertEqual(
            graph.calls[0][1]["metadata"],
            {
                "team_id": "team",
                "agent_id": "worker",
                "branch_id": "",
                "parent_logical_thread_key": "root",
                "parent_physical_thread_id": "root",
                "relation_id": "rel_worker",
                "logical_thread_key": "root:relation:rel_worker:agent:worker",
                "physical_thread_id": "root:relation:rel_worker:agent:worker",
                "run_id": "",
                "tool_call_edge_id": "call",
                "commit_id": "commit_call",
            },
        )

    def test_run_persists_tool_call_edge_success_and_failure(self) -> None:
        connection = sqlite3.connect(":memory:")
        success_graph = FakeGraph({"messages": [SimpleNamespace(content="answer")]})
        relation_config = relation(source="entry", target="worker", tool_name="ask_worker")
        tool = RelationTool(
            relation_config,
            Registry(success_graph),
            parent_thread_id="fallback",
            thread_id_factory=ThreadIdFactory(),
            checkpoint_metadata={},
            tool_call_edge_recorder=ToolCallEdgeRecorder(connection),
        )

        tool.run(
            "question",
            SimpleNamespace(
                config={
                    "configurable": {"thread_id": "root:branch:branch_01:mention:entry"},
                    "metadata": {"run_id": "run_01"},
                },
                state={},
                tool_call_id="call_success",
            ),
        )

        success_row = connection.execute(
            """
            select
                id,
                commit_id,
                branch_id,
                parent_logical_thread_key,
                parent_physical_thread_id,
                relation_id,
                target_agent_id,
                child_logical_thread_key,
                child_physical_thread_id,
                run_id,
                status
            from tool_call_edges
            where id = 'call_success'
            """
        ).fetchone()
        self.assertEqual(
            success_row,
            (
                "call_success",
                "commit_call_success",
                "branch_01",
                "root:mention:entry",
                "root:branch:branch_01:mention:entry",
                "rel_worker",
                "worker",
                "root:mention:entry:relation:rel_worker:agent:worker",
                "root:branch:branch_01:mention:entry:relation:rel_worker:agent:worker",
                "run_01",
                "success",
            ),
        )

        class FailingGraph:
            def invoke(self, *_args, **_kwargs):
                raise RuntimeError("boom")

        failing_tool = RelationTool(
            relation_config,
            Registry(FailingGraph()),
            parent_thread_id="fallback",
            thread_id_factory=ThreadIdFactory(),
            checkpoint_metadata={},
            tool_call_edge_recorder=ToolCallEdgeRecorder(connection),
        )
        with self.assertRaisesRegex(RuntimeError, "boom"):
            failing_tool.run(
                "question",
                SimpleNamespace(config={"configurable": {"thread_id": "root:branch:branch_01:mention:entry"}}, state={}, tool_call_id="call_failed"),
            )
        self.assertEqual(connection.execute("select status from tool_call_edges where id = 'call_failed'").fetchone()[0], "failed")

    def test_run_serializes_concurrent_calls_to_same_branch_and_logical_thread(self) -> None:
        class BlockingGraph:
            def __init__(self) -> None:
                self.active = 0
                self.max_active = 0
                self.lock = threading.Lock()

            def invoke(self, *_args, **_kwargs):
                with self.lock:
                    self.active += 1
                    self.max_active = max(self.max_active, self.active)
                time.sleep(0.02)
                with self.lock:
                    self.active -= 1
                return {"messages": [SimpleNamespace(content="answer")]}

        graph = BlockingGraph()
        tool = RelationTool(
            relation(source="entry", target="worker", tool_name="ask_worker"),
            Registry(graph),
            parent_thread_id="fallback",
            thread_id_factory=ThreadIdFactory(),
            checkpoint_metadata={},
        )
        runtime_one = SimpleNamespace(config={"configurable": {"thread_id": "root:branch:branch_01:mention:entry"}}, state={}, tool_call_id="call_1")
        runtime_two = SimpleNamespace(config={"configurable": {"thread_id": "root:branch:branch_01:mention:entry"}}, state={}, tool_call_id="call_2")
        threads = [
            threading.Thread(target=tool.run, args=("question", runtime_one)),
            threading.Thread(target=tool.run, args=("question", runtime_two)),
        ]

        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()

        self.assertEqual(graph.max_active, 1)

    def test_run_preserves_relation_identity_when_tool_name_changes(self) -> None:
        first_graph = FakeGraph({"messages": [SimpleNamespace(content="first")]})
        second_graph = FakeGraph({"messages": [SimpleNamespace(content="second")]})
        registry = Registry(first_graph)
        stable_relation = relation(source="entry", target="worker", tool_name="ask_worker", relation_id="stable-reviewer")
        renamed_relation = relation(source="entry", target="worker", tool_name="ask_better_worker", relation_id="stable-reviewer")

        first = RelationTool(stable_relation, registry, "fallback", ThreadIdFactory(), {})
        second = RelationTool(renamed_relation, Registry(second_graph), "fallback", ThreadIdFactory(), {})

        first.run("question", SimpleNamespace(config={"configurable": {"thread_id": "root:branch:branch_01:mention:entry"}}, state={}))
        second.run("question", SimpleNamespace(config={"configurable": {"thread_id": "root:branch:branch_01:mention:entry"}}, state={}))

        self.assertEqual(
            first_graph.calls[0][1]["configurable"]["thread_id"],
            "root:branch:branch_01:mention:entry:relation:stable-reviewer:agent:worker",
        )
        self.assertEqual(second_graph.calls[0][1]["configurable"]["thread_id"], first_graph.calls[0][1]["configurable"]["thread_id"])
        self.assertEqual(first_graph.calls[0][1]["metadata"]["branch_id"], "branch_01")
        self.assertEqual(
            first_graph.calls[0][1]["metadata"]["logical_thread_key"],
            "root:mention:entry:relation:stable-reviewer:agent:worker",
        )

    def test_parent_thread_falls_back_and_last_message_text_handles_result_shapes(self) -> None:
        tool = RelationTool(relation(), Registry(FakeGraph()), "fallback", ThreadIdFactory(), {})

        self.assertEqual(tool._parent_thread_id(SimpleNamespace(config=None)), "fallback")
        self.assertEqual(tool._last_message_text({"messages": [{"content": "dict-content"}]}), "dict-content")
        self.assertEqual(tool._last_message_text({"messages": [SimpleNamespace(content=None)]}), "")
        self.assertEqual(tool._last_message_text({"messages": []}), "{'messages': []}")
        self.assertEqual(tool._last_message_text("plain-result"), "plain-result")


class RelationToolFactoryTests(unittest.TestCase):
    def test_create_requires_tool_name_and_builds_structured_tool(self) -> None:
        team_config = team(agents={"entry": agent("entry", entrypoint=True), "worker": agent("worker")})

        with self.assertRaisesRegex(TeamInstanciatorError, "has no tool_name"):
            RelationToolFactory().create(team_config, relation(tool_name=None), Registry(FakeGraph()), "root", ThreadIdFactory())

        created = RelationToolFactory().create(
            team_config,
            relation(tool_name="ask_worker", description=None),
            Registry(FakeGraph()),
            "root",
            ThreadIdFactory(),
        )

        self.assertEqual(created.name, "ask_worker")
        self.assertEqual(created.description, "ask_worker")


if __name__ == "__main__":
    unittest.main()
