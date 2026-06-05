from __future__ import annotations

import unittest
from typing import Any

from src.team_instanciator.core.agent_graph import AgentGraph
from src.team_instanciator.core.agent_graph_registry import AgentGraphRegistry
from src.team_instanciator.runtime.checkpointer_handle import CheckpointerHandle
from tests.support import FakeGraph, agent, relation, team


class RecordingDeepAgentFactory:
    def __init__(self) -> None:
        self.calls: list[tuple[Any, Any, Any, list[Any], Any]] = []

    def create(self, team_config: Any, agent_config: Any, checkpointer_handle: Any, tools: list[Any], subagents: Any) -> FakeGraph:
        self.calls.append((team_config, agent_config, checkpointer_handle, tools, subagents))
        return FakeGraph({"messages": [{"content": agent_config.id}]})


class RecordingRelationToolFactory:
    def __init__(self) -> None:
        self.calls: list[tuple[Any, Any, Any, str, Any, Any, Any, Any]] = []

    def create(
        self,
        team_config: Any,
        relation_config: Any,
        registry: Any,
        parent_thread_id: str,
        thread_id_factory: Any,
        metadata_factory: Any,
        tool_call_edge_recorder: Any = None,
        branch_thread_resolver: Any = None,
    ) -> str:
        self.calls.append((team_config, relation_config, registry, parent_thread_id, thread_id_factory, metadata_factory, tool_call_edge_recorder, branch_thread_resolver))
        return f"tool:{relation_config.tool_name}"


class RecordingSubagentFactory:
    def __init__(self) -> None:
        self.calls: list[tuple[Any, Any, str]] = []

    def create(self, team_config: Any, registry: Any, agent_id: str) -> dict[str, str]:
        self.calls.append((team_config, registry, agent_id))
        return {"name": agent_id}


class AgentGraphRegistryTests(unittest.TestCase):
    def test_creates_and_caches_entrypoint_and_direct_agent_graphs(self) -> None:
        entry = agent("entry", entrypoint=True)
        worker = agent("worker")
        reviewer = agent("reviewer", kind="subagent")
        team_config = team(
            team_id="product",
            agents={"entry": entry, "worker": worker, "reviewer": reviewer},
            relations=(
                relation(source="entry", target="worker", relation_type="tool", tool_name="ask_worker"),
                relation(source="entry", target="reviewer", relation_type="subagent", tool_name=None),
                relation(source="worker", target="entry", relation_type="tool", tool_name="ask_entry"),
            ),
        )
        deep_factory = RecordingDeepAgentFactory()
        relation_factory = RecordingRelationToolFactory()
        subagent_factory = RecordingSubagentFactory()
        registry = AgentGraphRegistry(
            team_config,
            CheckpointerHandle("checkpointer"),
            deep_factory,
            subagent_factory,
            relation_factory,
            thread_id_factory=__import__("src.team_instanciator.runtime.thread_id_factory", fromlist=["ThreadIdFactory"]).ThreadIdFactory(),
        )

        entry_graph = registry.graph("entry")
        self.assertIs(entry_graph, registry.graph("entry"))
        worker_graph = registry.graph("worker")

        self.assertIsInstance(entry_graph, AgentGraph)
        self.assertIsInstance(worker_graph, AgentGraph)
        self.assertEqual(deep_factory.calls[0][3], ["tool:ask_worker"])
        self.assertEqual(deep_factory.calls[0][4], [{"name": "reviewer"}])
        self.assertEqual(deep_factory.calls[1][3], ["tool:ask_entry"])
        self.assertIsNone(deep_factory.calls[1][4])
        self.assertEqual(relation_factory.calls[0][3], "product")
        self.assertEqual(subagent_factory.calls, [(team_config, registry, "reviewer")])

        entry_graph.invoke("hello", config={"metadata": {}})
        worker_graph.invoke("hello", config={"metadata": {}})
        self.assertEqual(deep_factory.calls[0][0], team_config)


if __name__ == "__main__":
    unittest.main()
