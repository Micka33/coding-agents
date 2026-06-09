from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from src.team_instanciator.configuration.runtime_configuration import RuntimeConfiguration
from src.team_instanciator.factories.subagent_factory import SubagentFactory
from src.team_instanciator.resolvers.skills_resolver import SkillsResolver
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
        team_config = team(agents={"reviewer": agent("reviewer", description=None)})

        spec = factory.create(team_config, registry="registry", agent_id="reviewer")

        self.assertEqual(spec["name"], "reviewer")
        self.assertEqual(spec["description"], "reviewer")
        self.assertIs(spec["runnable"], langchain_factory.runnable)
        self.assertEqual(
            langchain_factory.runnable.config["configurable"],
            {
                "team_id": "team",
                "agent_id": "reviewer",
                "agent_name": "reviewer",
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
            agents={"reviewer": agent("reviewer", description="Reviews", prompt="Review prompt", skills="none")},
            relations=(relation(source="reviewer", target="reviewer", tool_name="ask_self"),),
        )

        spec = factory.create(team_config, registry="registry", agent_id="reviewer")

        self.assertEqual(spec["description"], "Reviews")
        self.assertEqual(spec["system_prompt"], "Review prompt")
        self.assertEqual(spec["tools"], ["builtin-tool", "relation-tool"])
        self.assertEqual(
            [(permission.operations, permission.mode) for permission in spec["permissions"]],
            [(["read"], "deny"), (["write"], "deny")],
        )
        self.assertIn("read_file", spec["middleware"][0].excluded_tools)
        self.assertIn("task", spec["middleware"][0].excluded_tools)
        self.assertIsInstance(relation_factory.calls[0][3], ThreadIdFactory)
        self.assertNotIn("skills", spec)

    def test_deepagents_runtime_includes_resolved_skill_sources(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            launch_cwd = Path(tmp) / "repo"
            (launch_cwd / ".agents" / "skills" / "project").mkdir(parents=True)
            (launch_cwd / ".agents" / "skills" / "project" / "SKILL.md").write_text("project", encoding="utf-8")
            factory = SubagentFactory(
                RuntimeResolver("deepagents_spec"),
                LangChainFactory(),
                ToolsetResolver(),
                RelationToolFactory(),
                ThreadIdFactory(),
                skills_resolver=SkillsResolver(RuntimeConfiguration({"CODEX_HOME": ""})),
            )
            team_config = team(
                working_directory=launch_cwd,
                load_cwd=launch_cwd,
                agents={"reviewer": agent("reviewer", skills={"only": ["project"]})},
            )

            spec = factory.create(team_config, registry="registry", agent_id="reviewer")

        self.assertEqual(spec["skills"], [("/skills/reviewer/project", "Project")])


if __name__ == "__main__":
    unittest.main()
