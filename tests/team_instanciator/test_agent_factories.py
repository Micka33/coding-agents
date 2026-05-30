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
        agent_config = agent("entry", name="Entry", prompt="System", debug=True)

        with patch("src.team_instanciator.factories.deep_agent_factory.create_deep_agent", return_value="graph") as create_deep_agent:
            created = DeepAgentFactory(
                Resolver("model"),
                ToolsetResolver(),
                Factory("backend"),
                Factory(["permissions"]),
                Resolver(["memory.md"]),
                Resolver(["skill-path"]),
            ).create(team_config, agent_config, CheckpointerHandle("checkpointer"), ["relation-tool"], [{"name": "sub"}])

        self.assertEqual(created, "graph")
        create_deep_agent.assert_called_once_with(
            name="Entry",
            model="model",
            tools=["builtin", "relation-tool"],
            system_prompt="System",
            subagents=[{"name": "sub"}],
            backend="backend",
            permissions=["permissions"],
            skills=["skill-path"],
            memory=["memory.md"],
            checkpointer="checkpointer",
            debug=True,
        )

    def test_langchain_agent_factory_passes_resolved_model_and_tools(self) -> None:
        team_config = team()
        agent_config = agent("entry", name="Entry", prompt="System", debug=True)

        with patch("src.team_instanciator.factories.langchain_agent_factory.create_agent", return_value="agent") as create_agent:
            created = LangChainAgentFactory(Resolver("model"), ToolsetResolver()).create(team_config, agent_config)

        self.assertEqual(created, "agent")
        create_agent.assert_called_once_with(
            model="model",
            tools=["langchain-tool"],
            system_prompt="System",
            name="Entry",
            debug=True,
        )


if __name__ == "__main__":
    unittest.main()
