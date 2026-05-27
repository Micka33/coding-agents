from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from deepagents.middleware.filesystem import _check_fs_permission
from langchain_core.tools import tool

from coding_agents.agent_factory import AgentFactory, normalize_agent_name
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
    def test_agent_factory_normalizes_common_agent_aliases(self) -> None:
        self.assertEqual(normalize_agent_name("architect"), "software-architect")
        self.assertEqual(normalize_agent_name("software_architect"), "software-architect")
        self.assertEqual(normalize_agent_name("engineering manager"), "engineering-manager")
        self.assertEqual(normalize_agent_name("reviewer"), "code-reviewer")
        self.assertEqual(normalize_agent_name("qa"), "qa-engineer")

    def test_agent_factory_creates_scout_and_implementation_subagent_specs(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            with patch(
                "coding_agents.agent_factory.create_scout_subagent",
                return_value={"name": "scout", "runnable": "compiled-scout"},
            ) as create_scout:
                factory = AgentFactory(
                    model="test:model",
                    scout_model="test:scout",
                    root_dir=root,
                    tools=[shared_test_tool],
                )

                scout_spec = factory.create_subagent_spec("scout")
                developer_spec = factory.create_subagent_spec("developer")

        self.assertEqual(scout_spec, {"name": "scout", "runnable": "compiled-scout"})
        create_scout.assert_called_once_with(
            model="test:scout",
            root_dir=root,
            tools=[shared_test_tool],
        )
        self.assertEqual(developer_spec["name"], "developer")
        self.assertIn("bounded development task", developer_spec["description"])
        self.assertIn("You are a developer", developer_spec["system_prompt"])
        self.assertEqual(developer_spec["tools"], [shared_test_tool])

    def test_agent_factory_creates_standalone_architect_agent(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            with (
                patch("coding_agents.agent_factory.disable_default_general_purpose_subagent") as disable_general_purpose,
                patch("coding_agents.vanilla_agent.create_deep_agent", return_value="architect-agent") as create_deep_agent,
            ):
                factory = AgentFactory(
                    model="test:model",
                    root_dir=Path(tmp),
                    backend="backend",
                    memory=("/AGENTS.md",),
                    checkpointer="checkpointer",
                )

                agent = factory.create("architect")

        self.assertEqual(agent, "architect-agent")
        disable_general_purpose.assert_called_once_with("test:model")
        kwargs = create_deep_agent.call_args.kwargs
        self.assertEqual(kwargs["name"], "software-architect")
        self.assertEqual(kwargs["model"], "test:model")
        self.assertEqual(kwargs["backend"], "backend")
        self.assertEqual(kwargs["memory"], ["/AGENTS.md"])
        self.assertEqual(kwargs["checkpointer"], "checkpointer")
        self.assertNotIn("skills", kwargs)
        self.assertIn("Resident-agent behavior", kwargs["system_prompt"])

    def test_agent_factory_creates_standalone_developer_with_implementation_permissions(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            with (
                patch("coding_agents.agent_factory.disable_default_general_purpose_subagent"),
                patch("coding_agents.vanilla_agent.create_deep_agent", return_value="developer-agent") as create_deep_agent,
            ):
                factory = AgentFactory(
                    model="test:model",
                    root_dir=Path(tmp),
                    backend="backend",
                    tools=[shared_test_tool],
                    mode="implementation",
                )

                agent = factory.create("developer")

        self.assertEqual(agent, "developer-agent")
        kwargs = create_deep_agent.call_args.kwargs
        self.assertEqual(kwargs["name"], "developer")
        self.assertEqual(kwargs["tools"], [shared_test_tool])
        self.assertIn("You are a developer", kwargs["system_prompt"])
        self.assertEqual(_check_fs_permission(kwargs["permissions"], "write", "/README.md"), "allow")

    def test_agent_factory_creates_engineering_manager_with_subagents_and_manager_tools(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            with (
                patch("coding_agents.agent_factory.disable_default_general_purpose_subagent"),
                patch("coding_agents.vanilla_agent.create_deep_agent", return_value="manager-agent") as create_deep_agent,
            ):
                factory = AgentFactory(
                    model="test:model",
                    root_dir=Path(tmp),
                    backend="backend",
                    tools=[],
                    skills=("skills/custom",),
                )

                agent = factory.create(
                    "engineering-manager",
                    manager_tools=[shared_test_tool],
                    subagents=[{"name": "scout"}],
                    auto_transition=True,
                )

        self.assertEqual(agent, "manager-agent")
        kwargs = create_deep_agent.call_args.kwargs
        self.assertEqual(kwargs["name"], "engineering-manager")
        self.assertEqual(kwargs["tools"], [shared_test_tool])
        self.assertEqual(kwargs["subagents"], [{"name": "scout"}])
        self.assertEqual(kwargs["skills"], ["skills/custom"])
        self.assertIn("Current mode: auto-shaping", kwargs["system_prompt"])

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
