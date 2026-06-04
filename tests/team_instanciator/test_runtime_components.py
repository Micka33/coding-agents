from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from src.team_instanciator.resolvers.agent_runtime_resolver import AgentRuntimeResolver
from src.team_instanciator.resolvers.memory_resolver import MemoryResolver
from src.team_instanciator.factories.permissions_factory import PermissionsFactory
from src.team_instanciator.resolvers.root_dir_resolver import RootDirResolver
from src.team_instanciator.configuration.runtime_configuration import RuntimeConfiguration
from src.team_instanciator.runtime.runtime_lane import RuntimeLane
from src.team_instanciator.resolvers.skills_resolver import SkillsResolver
from src.team_instanciator.errors.team_instanciator_error import TeamInstanciatorError
from src.team_instanciator.manifest.team_runtime_manifest import TeamRuntimeManifest
from src.team_instanciator.runtime.thread_id_factory import ThreadIdFactory
from tests.support import agent, defaults, relation, team


class RuntimeComponentsTests(unittest.TestCase):
    def test_agent_runtime_resolver_selects_langchain_for_readonly_web_subagents(self) -> None:
        resolver = AgentRuntimeResolver()

        self.assertEqual(resolver.subagent_runtime(agent(kind="subagent", toolsets=("scoped_read_tools",))), "langchain")
        self.assertEqual(resolver.subagent_runtime(agent(kind="subagent", toolsets=("web", "scoped_read_tools"))), "langchain")
        self.assertEqual(resolver.subagent_runtime(agent(kind="subagent", toolsets=("shell",))), "deepagents_spec")
        self.assertEqual(resolver.subagent_runtime(agent(kind="deepagent", toolsets=("scoped_read_tools",))), "deepagents_spec")

    def test_memory_resolver_handles_none_explicit_lists_defaults_and_missing_errors(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "memory.md").write_text("remember", encoding="utf-8")
            team_config = team(team_defaults=defaults(root_dir=root, memory_candidates=("memory.md", "missing.md", object())))
            resolver = MemoryResolver()

            self.assertIsNone(resolver.resolve(team_config, agent(memory="none")))
            self.assertEqual(resolver.resolve(team_config, agent(memory=["memory.md", object()])), ["memory.md"])
            self.assertEqual(resolver.resolve(team_config, agent(memory="inherit")), ["memory.md"])

            with self.assertRaisesRegex(TeamInstanciatorError, "Memory file does not exist"):
                resolver.resolve(
                    team(team_defaults=defaults(root_dir=root, memory_candidates=("missing.md",), memory_error_when_missing=True)),
                    agent(memory="inherit"),
                )

    def test_permissions_factory_allows_or_denies_read_and_write_by_toolset(self) -> None:
        readonly = PermissionsFactory().create(agent(toolsets=("scoped_read_tools",)))
        writer = PermissionsFactory().create(agent(toolsets=("write",)))

        self.assertEqual([(permission.operations, permission.mode) for permission in readonly], [(["read"], "allow"), (["write"], "deny")])
        self.assertEqual([(permission.operations, permission.mode) for permission in writer], [(["read"], "deny"), (["write"], "allow")])

    def test_root_dir_runtime_lane_manifest_and_thread_ids(self) -> None:
        absolute = Path.cwd()
        self.assertEqual(RootDirResolver().resolve(team(team_defaults=defaults(root_dir=absolute))), absolute)
        self.assertEqual(RootDirResolver().resolve(team(team_defaults=defaults(root_dir="relative-root"))), Path("relative-root").resolve())

        entrypoint_lane = RuntimeLane("entrypoint:entry", "entrypoint", "entry", "Entry", thread_id_pattern="{parent_thread_id}")
        relation_lane = RuntimeLane(
            "relation:rel_worker",
            "tool-relation",
            "worker",
            "Worker",
            relation_id="rel_worker",
            source_agent_id="entry",
            target_agent_id="worker",
            tool_name="ask_worker",
            thread_id_pattern="{parent_thread_id}:relation:rel_worker:agent:worker",
        )
        manifest = TeamRuntimeManifest("team", 1, (entrypoint_lane, relation_lane))
        relation_config = relation(source="entry", target="worker", tool_name=None)
        thread_factory = ThreadIdFactory()

        self.assertEqual(entrypoint_lane.thread_id("root"), "root")
        self.assertIsNone(RuntimeLane("task", "task-subagent-type", "worker", "Worker").thread_id("root"))
        self.assertEqual(relation_lane.to_dict("root")["thread_id"], "root:relation:rel_worker:agent:worker")
        self.assertEqual(manifest.lanes_for("root")[0]["thread_id"], "root")
        self.assertEqual(manifest.to_dict()["team_id"], "team")
        self.assertEqual(thread_factory.root("team"), "team")
        self.assertEqual(thread_factory.relation("root", relation_config), "root:relation:rel_worker:agent:worker")
        self.assertEqual(thread_factory.relation_pattern(relation_config), "{parent_thread_id}:relation:rel_worker:agent:worker")
        self.assertEqual(thread_factory.branch_id_from_thread_id("root:branch:branch_01:mention:agent"), "branch_01")
        self.assertEqual(thread_factory.logical_thread_key("root:branch:branch_01:mention:agent"), "root:mention:agent")
        parsed = thread_factory.parse_relation_thread_id("root:relation:rel_worker:agent:worker")
        self.assertIsNotNone(parsed)
        self.assertEqual(parsed.relation_id, "rel_worker")
        self.assertEqual(parsed.target_agent_id, "worker")
        self.assertEqual(thread_factory.mention("root", "architect"), "root:mention:architect")
        self.assertEqual(thread_factory.mention_pattern("architect"), "{parent_thread_id}:mention:architect")
        self.assertEqual(thread_factory.parse_relation_thread_id("root:entry:ask_worker:worker").tool_name, "ask_worker")
        self.assertIsNone(thread_factory.parse_relation_thread_id("bad"))
        self.assertIsNone(thread_factory.parse_relation_thread_id("root:entry::worker"))

    def test_skills_resolver_handles_inherit_none_non_lists_project_user_and_fallback_paths(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "repo"
            home = Path(tmp) / "codex-home"
            (root / ".agents" / "skills" / "project").mkdir(parents=True)
            (root / ".agents" / "skills" / "project" / "SKILL.md").write_text("project", encoding="utf-8")
            (home / "skills" / "user").mkdir(parents=True)
            (home / "skills" / "user" / "SKILL.md").write_text("user", encoding="utf-8")
            resolver = SkillsResolver(RuntimeConfiguration({"CODEX_HOME": str(home)}))
            team_config = team(team_defaults=defaults(root_dir=root))

            self.assertIsNone(resolver.resolve(team_config, agent(skills=None)))
            self.assertIsNone(resolver.resolve(team_config, agent(skills="inherit")))
            self.assertIsNone(resolver.resolve(team_config, agent(skills="none")))
            self.assertIsNone(resolver.resolve(team_config, agent(skills="project")))

            resolved = resolver.resolve(team_config, agent(skills=["project", "user", "missing", object()]))

        self.assertEqual(
            resolved,
            [
                str(root / ".agents" / "skills" / "project"),
                str(home / "skills" / "user"),
                str(root / ".agents" / "skills" / "missing"),
            ],
        )


if __name__ == "__main__":
    unittest.main()
