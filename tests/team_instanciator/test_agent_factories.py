from __future__ import annotations

import unittest
from unittest.mock import patch

from src.team_instanciator.runtime.checkpointer_handle import CheckpointerHandle
from src.team_instanciator.factories.deep_agent_factory import DeepAgentFactory
from src.team_instanciator.factories.langchain_agent_factory import LangChainAgentFactory
from tests.support import agent, team


class Resolver:
    def __init__(self, value):
        self.value = value

    def resolve(self, *args):
        return self.value


class ToolsetResolver:
    def resolve_for_deepagents(self, *args):
        return ["builtin"]

    def resolve_for_langchain(self, *args):
        return ["langchain-tool"]


class Factory:
    def __init__(self, value):
        self.value = value

    def create(self, *args):
        return self.value


class AgentFactoryTests(unittest.TestCase):
    def test_deep_agent_factory_passes_resolved_dependencies_to_deepagents(self) -> None:
        team_config = team()
        agent_config = agent("entry", prompt="System", debug=True)

        with (
            patch(
                "src.team_instanciator.factories.deep_agent_factory.create_deep_agent",
                return_value="graph",
            ) as create_deep_agent,
            patch(
                "src.team_instanciator.factories.deep_agent_factory.register_harness_profile"
            ) as register_profile,
        ):
            created = DeepAgentFactory(
                Resolver("model"),
                ToolsetResolver(),
                Factory("backend"),
                Factory(["permissions"]),
                Resolver(["memory.md"]),
                Resolver(["skill-path"]),
            ).create(
                team_config,
                agent_config,
                CheckpointerHandle("checkpointer"),
                ["relation-tool"],
                [{"name": "sub"}],
            )

        self.assertEqual(created, "graph")
        register_profile.assert_called_once()
        self.assertEqual(register_profile.call_args.args[0], "model")
        kwargs = create_deep_agent.call_args.kwargs
        self.assertEqual(kwargs["name"], "entry")
        self.assertEqual(kwargs["model"], "model")
        self.assertEqual(kwargs["tools"], ["builtin", "relation-tool"])
        self.assertEqual(kwargs["system_prompt"], "System")
        self.assertEqual(kwargs["subagents"], [{"name": "sub"}])
        self.assertEqual(kwargs["backend"], "backend")
        self.assertEqual(kwargs["permissions"], ["permissions"])
        self.assertEqual(kwargs["skills"], ["skill-path"])
        self.assertEqual(kwargs["memory"], ["memory.md"])
        self.assertEqual(kwargs["checkpointer"], "checkpointer")
        self.assertIs(kwargs["debug"], True)
        self.assertNotIn("task", kwargs["middleware"][0].excluded_tools)
        self.assertIn("read_file", kwargs["middleware"][0].excluded_tools)

    def test_deep_agent_factory_adds_general_purpose_subagent_only_when_enabled(self) -> None:
        team_config = team()

        with (
            patch(
                "src.team_instanciator.factories.deep_agent_factory.create_deep_agent",
                return_value="graph",
            ) as create_deep_agent,
            patch("src.team_instanciator.factories.deep_agent_factory.register_harness_profile"),
        ):
            DeepAgentFactory(
                Resolver("model"),
                ToolsetResolver(),
                Factory("backend"),
                Factory(["permissions"]),
                Resolver(["memory.md"]),
                Resolver(["skill-path"]),
            ).create(
                team_config,
                agent("entry", enable_general_purpose_subagent=True),
                CheckpointerHandle("checkpointer"),
                [],
                [{"name": "translator"}],
            )

        subagents = create_deep_agent.call_args.kwargs["subagents"]
        self.assertEqual([spec["name"] for spec in subagents], ["translator", "general-purpose"])
        self.assertEqual(subagents[1]["permissions"], ["permissions"])
        self.assertIn("task", subagents[1]["middleware"][0].excluded_tools)
        self.assertNotIn(
            "task",
            create_deep_agent.call_args.kwargs["middleware"][0].excluded_tools,
        )

        with (
            patch(
                "src.team_instanciator.factories.deep_agent_factory.create_deep_agent",
                return_value="graph",
            ) as create_deep_agent,
            patch("src.team_instanciator.factories.deep_agent_factory.register_harness_profile"),
        ):
            DeepAgentFactory(
                Resolver("model"),
                ToolsetResolver(),
                Factory("backend"),
                Factory(["permissions"]),
                Resolver(["memory.md"]),
                Resolver(["skill-path"]),
            ).create(
                team_config,
                agent("entry", enable_general_purpose_subagent=False),
                CheckpointerHandle("checkpointer"),
                [],
                [{"name": "translator"}],
            )

        self.assertEqual(create_deep_agent.call_args.kwargs["subagents"], [{"name": "translator"}])

    def test_langchain_agent_factory_passes_resolved_model_and_tools(self) -> None:
        team_config = team()
        agent_config = agent("entry", prompt="System", debug=True)

        with patch("src.team_instanciator.factories.langchain_agent_factory.create_agent", return_value="agent") as create_agent:
            created = LangChainAgentFactory(Resolver("model"), ToolsetResolver()).create(team_config, agent_config)

        self.assertEqual(created, "agent")
        create_agent.assert_called_once_with(
            model="model",
            tools=["langchain-tool"],
            system_prompt="System",
            name="entry",
            debug=True,
        )


if __name__ == "__main__":
    unittest.main()
