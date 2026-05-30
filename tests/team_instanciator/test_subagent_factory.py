from __future__ import annotations

import unittest

from src.team_instanciator.factories.subagent_factory import SubagentFactory
from src.team_instanciator.runtime.thread_id_factory import ThreadIdFactory
from tests.support import agent, relation, team


class RuntimeResolver:
    def __init__(self, runtime: str) -> None:
        self.runtime = runtime

    def subagent_runtime(self, agent_config) -> str:
        return self.runtime


class Runnable:
    def __init__(self) -> None:
        self.config = None

    def with_config(self, config):
        self.config = config
        return self


class LangChainFactory:
    def __init__(self) -> None:
        self.runnable = Runnable()

    def create(self, *args):
        return self.runnable


class ToolsetResolver:
    def resolve_for_deepagents(self, *args):
        return ["builtin-tool"]


class RelationToolFactory:
    def __init__(self) -> None:
        self.calls = []

    def create(self, *args):
        self.calls.append(args)
        return "relation-tool"


class SubagentFactoryTests(unittest.TestCase):
    def test_langchain_runtime_returns_configured_runnable_spec(self) -> None:
        langchain_factory = LangChainFactory()
        factory = SubagentFactory(
            RuntimeResolver("langchain"),
            langchain_factory,
            ToolsetResolver(),
            RelationToolFactory(),
            ThreadIdFactory(),
        )
        team_config = team(agents={"reviewer": agent("reviewer", name="Reviewer", description=None)})

        spec = factory.create(team_config, registry="registry", agent_id="reviewer")

        self.assertEqual(spec["name"], "Reviewer")
        self.assertEqual(spec["description"], "Reviewer")
        self.assertIs(spec["runnable"], langchain_factory.runnable)
        self.assertEqual(
            langchain_factory.runnable.config["configurable"],
            {
                "team_id": "team",
                "agent_id": "reviewer",
                "agent_name": "Reviewer",
                "thread_kind": "task-subagent",
                "lane_id": "task-subagent-type:reviewer",
            },
        )

    def test_deepagents_runtime_returns_prompt_and_tool_spec(self) -> None:
        relation_factory = RelationToolFactory()
        factory = SubagentFactory(
            RuntimeResolver("deepagents_spec"),
            LangChainFactory(),
            ToolsetResolver(),
            relation_factory,
            ThreadIdFactory(),
        )
        team_config = team(
            agents={"reviewer": agent("reviewer", name="Reviewer", description="Reviews", prompt="Review prompt")},
            relations=(relation(source="reviewer", target="reviewer", tool_name="ask_self"),),
        )

        spec = factory.create(team_config, registry="registry", agent_id="reviewer")

        self.assertEqual(spec["description"], "Reviews")
        self.assertEqual(spec["system_prompt"], "Review prompt")
        self.assertEqual(spec["tools"], ["builtin-tool", "relation-tool"])
        self.assertEqual(relation_factory.calls[0][3], "team")


if __name__ == "__main__":
    unittest.main()
