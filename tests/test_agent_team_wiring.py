from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from langchain_core.tools import tool

from coding_agents.resident_agents import ResidentAgentTeam
from coding_agents.scout import create_scout_subagent


@tool
def shared_test_tool(query: str) -> str:
    """Shared test tool for scout wiring."""

    return query


class FakeResidentAgent:
    def __init__(self, response: str) -> None:
        self.response = response
        self.calls: list[tuple[dict[str, object], dict[str, object]]] = []

    def invoke(self, payload: dict[str, object], *, config: dict[str, object]) -> dict[str, object]:
        self.calls.append((payload, config))
        return {"messages": [SimpleNamespace(content=self.response)]}


class AgentTeamWiringTests(unittest.TestCase):
    def test_resident_manager_tools_route_to_stable_thread_ids(self) -> None:
        product_agent = FakeResidentAgent("product ok")
        architect_agent = FakeResidentAgent("architect ok")
        resident_team = ResidentAgentTeam(
            product_agent=product_agent,
            architect_agent=architect_agent,
            product_thread_id="parent:resident:product-analyst",
            architect_thread_id="parent:resident:software-architect",
        )

        manager_tools = resident_team.manager_tools()
        tools_by_name = {tool.name: tool for tool in manager_tools}

        self.assertEqual(set(tools_by_name), {"ask_product_analyst", "ask_software_architect"})
        self.assertIn("product", tools_by_name["ask_product_analyst"].description)
        self.assertIn("architecture", tools_by_name["ask_software_architect"].description)
        self.assertEqual(
            tools_by_name["ask_product_analyst"].invoke({"message": "prioritize this"}),
            "product ok",
        )
        self.assertEqual(
            tools_by_name["ask_software_architect"].invoke({"message": "decide this"}),
            "architect ok",
        )

        product_payload, product_config = product_agent.calls[0]
        architect_payload, architect_config = architect_agent.calls[0]
        self.assertEqual(product_payload, {"messages": [{"role": "user", "content": "prioritize this"}]})
        self.assertEqual(architect_payload, {"messages": [{"role": "user", "content": "decide this"}]})
        self.assertEqual(
            product_config,
            {"configurable": {"thread_id": "parent:resident:product-analyst"}},
        )
        self.assertEqual(
            architect_config,
            {"configurable": {"thread_id": "parent:resident:software-architect"}},
        )

    def test_scout_subagent_registers_scoped_tools_plus_shared_tools_without_execute(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            with patch("coding_agents.scout.create_agent", return_value="compiled-scout") as create_agent:
                spec = create_scout_subagent(
                    model="test:model",
                    root_dir=Path(tmp),
                    tools=[shared_test_tool],
                )

        self.assertEqual(spec["name"], "scout")
        self.assertEqual(spec["runnable"], "compiled-scout")
        kwargs = create_agent.call_args.kwargs
        self.assertEqual(kwargs["model"], "test:model")
        self.assertEqual(kwargs["name"], "scout")
        tool_names = [tool.name for tool in kwargs["tools"]]
        self.assertEqual(tool_names[:4], ["ls", "read_file", "glob", "grep"])
        self.assertIn("shared_test_tool", tool_names)
        self.assertNotIn("execute", tool_names)


if __name__ == "__main__":
    unittest.main()
