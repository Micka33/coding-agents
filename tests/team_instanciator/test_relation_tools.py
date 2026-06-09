from __future__ import annotations

import sqlite3
import threading
import time
import unittest
from types import SimpleNamespace

from src.team_instanciator.tools.relation_tool import RelationTool
from src.team_instanciator.conversation.store import ConversationStore
from src.team_instanciator.factories.relation_tool_factory import RelationToolFactory
from src.team_instanciator.errors.team_instanciator_error import TeamInstanciatorError
from src.team_instanciator.runtime.branch_thread_resolver import BranchThreadResolver
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
    def test_base_child_config_carries_callbacks_when_present(self) -> None:
        tool = RelationTool.__new__(RelationTool)

        config = tool._base_child_config(
            SimpleNamespace(config={"callbacks": ["callback"]}),
            "thread:branch:branch_main:mention:entry",
        )

        self.assertEqual(config["callbacks"], ["callback"])

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
        self.assertEqual(graph.async_calls, 1)
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

    def test_run_continues_persisted_branch_thread_for_relation_key(self) -> None:
        connection = sqlite3.connect(":memory:")
        graph = FakeGraph({"messages": [SimpleNamespace(content="answer")]})
        relation_config = relation(source="entry", target="worker", tool_name="ask_worker")
        thread_id_factory = ThreadIdFactory()
        store = ConversationStore(team_id="team", conversation_id="thread", connection=connection)
        branch = store.create_branch(label="Edit", parent_branch_id="branch_main")
        logical_thread_key = "thread:mention:entry:relation:rel_worker:agent:worker"
        store.ensure_branch_thread(
            branch_id=branch.id,
            logical_thread_key=logical_thread_key,
            physical_thread_id="persisted-worker-thread",
        )
        tool = RelationTool(
            relation_config,
            Registry(graph),
            parent_thread_id="fallback",
            thread_id_factory=thread_id_factory,
            checkpoint_metadata={},
            tool_call_edge_recorder=ToolCallEdgeRecorder(connection),
            branch_thread_resolver=BranchThreadResolver(connection, "team"),
        )

        tool.run(
            "question",
            SimpleNamespace(
                config={"configurable": {"thread_id": f"thread:branch:{branch.id}:mention:entry"}},
                state={},
                tool_call_id="call_persisted",
            ),
        )

        persisted_edge = connection.execute(
            "select child_logical_thread_key, child_physical_thread_id from tool_call_edges where id = 'call_persisted'"
        ).fetchone()
        self.assertEqual(graph.calls[0][1]["configurable"]["thread_id"], "persisted-worker-thread")
        self.assertEqual(persisted_edge, (logical_thread_key, "persisted-worker-thread"))

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

    def test_run_keeps_same_target_histories_separate_for_different_parents(self) -> None:
        connection = sqlite3.connect(":memory:")
        graph = FakeGraph({"messages": [SimpleNamespace(content="answer")]})
        tool = RelationTool(
            relation(source="entry", target="worker", tool_name="ask_worker", relation_id="stable-worker"),
            Registry(graph),
            parent_thread_id="fallback",
            thread_id_factory=ThreadIdFactory(),
            checkpoint_metadata={},
            branch_thread_resolver=BranchThreadResolver(connection, "team"),
        )

        tool.run(
            "entry question",
            SimpleNamespace(config={"configurable": {"thread_id": "root:branch:branch_01:mention:entry"}}, state={}),
        )
        tool.run(
            "reviewer question",
            SimpleNamespace(config={"configurable": {"thread_id": "root:branch:branch_01:mention:reviewer"}}, state={}),
        )

        thread_ids = [call[1]["configurable"]["thread_id"] for call in graph.calls]
        rows = connection.execute(
            """
            select logical_thread_key, physical_thread_id
            from team_conversation_branch_threads
            where branch_id = 'branch_01'
            order by logical_thread_key
            """
        ).fetchall()

        self.assertNotEqual(thread_ids[0], thread_ids[1])
        self.assertEqual(
            rows,
            [
                (
                    "root:mention:entry:relation:stable-worker:agent:worker",
                    "root:branch:branch_01:mention:entry:relation:stable-worker:agent:worker",
                ),
                (
                    "root:mention:reviewer:relation:stable-worker:agent:worker",
                    "root:branch:branch_01:mention:reviewer:relation:stable-worker:agent:worker",
                ),
            ],
        )

    def test_run_keeps_same_target_histories_separate_for_different_relations(self) -> None:
        connection = sqlite3.connect(":memory:")
        first_graph = FakeGraph({"messages": [SimpleNamespace(content="first")]})
        second_graph = FakeGraph({"messages": [SimpleNamespace(content="second")]})
        first_tool = RelationTool(
            relation(source="entry", target="worker", tool_name="ask_primary", relation_id="primary-worker"),
            Registry(first_graph),
            parent_thread_id="fallback",
            thread_id_factory=ThreadIdFactory(),
            checkpoint_metadata={},
            branch_thread_resolver=BranchThreadResolver(connection, "team"),
        )
        second_tool = RelationTool(
            relation(source="entry", target="worker", tool_name="ask_secondary", relation_id="secondary-worker"),
            Registry(second_graph),
            parent_thread_id="fallback",
            thread_id_factory=ThreadIdFactory(),
            checkpoint_metadata={},
            branch_thread_resolver=BranchThreadResolver(connection, "team"),
        )
        runtime = SimpleNamespace(config={"configurable": {"thread_id": "root:branch:branch_01:mention:entry"}}, state={})

        first_tool.run("primary question", runtime)
        second_tool.run("secondary question", runtime)

        first_thread_id = first_graph.calls[0][1]["configurable"]["thread_id"]
        second_thread_id = second_graph.calls[0][1]["configurable"]["thread_id"]
        rows = connection.execute(
            """
            select logical_thread_key, physical_thread_id
            from team_conversation_branch_threads
            where branch_id = 'branch_01'
            order by logical_thread_key
            """
        ).fetchall()

        self.assertNotEqual(first_thread_id, second_thread_id)
        self.assertEqual(
            rows,
            [
                (
                    "root:mention:entry:relation:primary-worker:agent:worker",
                    "root:branch:branch_01:mention:entry:relation:primary-worker:agent:worker",
                ),
                (
                    "root:mention:entry:relation:secondary-worker:agent:worker",
                    "root:branch:branch_01:mention:entry:relation:secondary-worker:agent:worker",
                ),
            ],
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
