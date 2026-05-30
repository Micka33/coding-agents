from __future__ import annotations

import asyncio
import unittest
from typing import Any

from src.team_instanciator.agent_graph import AgentGraph


class RecordingGraph:
    def __init__(self) -> None:
        self.calls: list[tuple[str, Any, dict[str, Any]]] = []
        self.marker = "delegated"

    def invoke(self, input: Any, config: Any = None, **kwargs: Any) -> dict[str, Any]:
        self.calls.append(("invoke", config, kwargs))
        return {"input": input, "config": config}

    async def ainvoke(self, input: Any, config: Any = None, **kwargs: Any) -> dict[str, Any]:
        self.calls.append(("ainvoke", config, kwargs))
        return {"input": input, "config": config}

    def stream(self, input: Any, config: Any = None, **kwargs: Any):
        self.calls.append(("stream", config, kwargs))
        return iter([{"input": input, "config": config}])

    async def astream(self, input: Any, config: Any = None, **kwargs: Any):
        self.calls.append(("astream", config, kwargs))
        yield {"input": input, "config": config}

    async def astream_events(self, input: Any, config: Any = None, **kwargs: Any):
        self.calls.append(("astream_events", config, kwargs))
        yield {"event": input, "config": config}

    def batch(self, inputs: list[Any], config: Any = None, **kwargs: Any) -> list[Any]:
        self.calls.append(("batch", config, kwargs))
        return inputs

    async def abatch(self, inputs: list[Any], config: Any = None, **kwargs: Any) -> list[Any]:
        self.calls.append(("abatch", config, kwargs))
        return inputs

    def with_config(self, config: Any = None, **kwargs: Any) -> RecordingGraph:
        self.calls.append(("with_config", config, kwargs))
        child = RecordingGraph()
        child.marker = "configured"
        return child


class AgentGraphTests(unittest.TestCase):
    def test_delegates_sync_async_batch_and_attribute_access_with_metadata(self) -> None:
        graph = RecordingGraph()
        wrapped = AgentGraph(graph, {"team_id": "team", "count": 1, "ignored": object()})

        result = wrapped.invoke({"hello": "world"}, config={"metadata": {"count": 2}}, tag="sync")
        self.assertEqual(result["config"]["metadata"], {"team_id": "team", "count": 2})
        self.assertEqual(list(wrapped.stream("input")), [{"input": "input", "config": {"metadata": {"team_id": "team", "count": 1}}}])
        self.assertEqual(wrapped.batch([1, 2], config=[None, {"metadata": {"lane": "custom"}}]), [1, 2])
        self.assertEqual(wrapped.marker, "delegated")

        async def run_async_calls() -> None:
            self.assertEqual((await wrapped.ainvoke("async"))["config"]["metadata"]["team_id"], "team")
            self.assertEqual([chunk async for chunk in wrapped.astream("stream")][0]["config"]["metadata"]["team_id"], "team")
            self.assertEqual([event async for event in wrapped.astream_events("event")][0]["config"]["metadata"]["team_id"], "team")
            self.assertEqual(await wrapped.abatch(["a"], config={"metadata": {"agent": "one"}}), ["a"])

        asyncio.run(run_async_calls())
        self.assertEqual(graph.calls[2][1], [{"metadata": {"team_id": "team", "count": 1}}, {"metadata": {"team_id": "team", "count": 1, "lane": "custom"}}])

    def test_with_config_returns_wrapped_configured_graph(self) -> None:
        graph = RecordingGraph()
        wrapped = AgentGraph(graph, {"team_id": "team"})

        configured = wrapped.with_config({"metadata": {"agent_id": "agent"}}, configurable={"thread_id": "one"})

        self.assertIsInstance(configured, AgentGraph)
        self.assertEqual(configured.marker, "configured")
        self.assertEqual(graph.calls[0], ("with_config", {"metadata": {"team_id": "team", "agent_id": "agent"}}, {"configurable": {"thread_id": "one"}}))


if __name__ == "__main__":
    unittest.main()
