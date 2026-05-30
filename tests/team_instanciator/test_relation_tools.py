from __future__ import annotations

import unittest
from types import SimpleNamespace

from src.team_instanciator.relation_tool import RelationTool
from src.team_instanciator.relation_tool_factory import RelationToolFactory
from src.team_instanciator.team_instanciator_error import TeamInstanciatorError
from src.team_instanciator.thread_id_factory import ThreadIdFactory
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
        self.assertEqual(graph.calls[0][1]["configurable"]["thread_id"], "root:entry:ask_worker:worker")
        self.assertEqual(graph.calls[0][1]["metadata"], {"team_id": "team", "agent_id": "worker"})

    def test_parent_thread_falls_back_and_last_message_text_handles_result_shapes(self) -> None:
        tool = RelationTool(relation(), Registry(FakeGraph()), "fallback", ThreadIdFactory(), {})

        self.assertEqual(tool._parent_thread_id(SimpleNamespace(config=None)), "fallback")
        self.assertEqual(tool._last_message_text({"messages": [{"content": "dict-content"}]}), "dict-content")
        self.assertEqual(tool._last_message_text({"messages": [SimpleNamespace(content=None)]}), "")
        self.assertEqual(tool._last_message_text({"messages": []}), "{'messages': []}")
        self.assertEqual(tool._last_message_text("plain-result"), "plain-result")


class RelationToolFactoryTests(unittest.TestCase):
    def test_create_requires_tool_name_and_builds_structured_tool(self) -> None:
        team_config = team(agents={"entry": agent("entry", entrypoint=True), "worker": agent("worker", name="Worker")})

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
