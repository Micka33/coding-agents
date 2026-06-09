from __future__ import annotations

import asyncio
import sqlite3
import tempfile
import threading
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from src.team_instanciator.resolvers.agent_runtime_resolver import AgentRuntimeResolver
from src.team_instanciator.resolvers.memory_resolver import MemoryResolver
from src.team_instanciator.factories.permissions_factory import PermissionsFactory
from src.team_instanciator.factories.tool_visibility_factory import ToolVisibilityFactory
from src.team_loader.resolvers.working_directory_resolver import WorkingDirectoryResolver
from src.team_instanciator.configuration.runtime_configuration import RuntimeConfiguration
from src.team_instanciator.runtime.runtime_lane import RuntimeLane
from src.team_instanciator.runtime.async_checkpointer_loop import AsyncCheckpointerLoop
from src.team_instanciator.runtime.branch_thread_resolver import BranchThreadResolver
from src.team_instanciator.runtime.graph_invocation import invoke_graph_sync
from src.team_instanciator.resolvers.skills_resolver import SkillsResolver
from src.team_instanciator.resolvers.skill_source_resolver import SkillSourceResolver
from src.team_instanciator.errors.team_instanciator_error import TeamInstanciatorError
from src.team_instanciator.manifest.team_runtime_manifest import TeamRuntimeManifest
from src.team_instanciator.runtime.thread_id_factory import ThreadIdFactory
from src.team_instanciator.runtime.thread_ids import ThreadIdV1Codec
from src.team_instanciator.tools.deep_agent_tool_visibility_middleware import DeepAgentToolVisibilityMiddleware
from tests.support import agent, defaults, relation, team


class FakeModelRequest:
    def __init__(self, tools: list[object]) -> None:
        self.tools = tools

    def override(self, **overrides):
        return FakeModelRequest(overrides.get("tools", self.tools))


async def _async_value(value):
    return value


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
            team_config = team(
                working_directory=root,
                team_defaults=defaults(memory_candidates=("memory.md", "missing.md", object())),
            )
            resolver = MemoryResolver()

            self.assertIsNone(resolver.resolve(team_config, agent(memory="none")))
            self.assertEqual(resolver.resolve(team_config, agent(memory=["memory.md", object()])), ["memory.md"])
            self.assertEqual(resolver.resolve(team_config, agent(memory="inherit")), ["memory.md"])

            with self.assertRaisesRegex(TeamInstanciatorError, "Memory file does not exist"):
                resolver.resolve(
                    team(
                        working_directory=root,
                        team_defaults=defaults(memory_candidates=("missing.md",), memory_error_when_missing=True),
                    ),
                    agent(memory="inherit"),
                )

    def test_permissions_factory_allows_or_denies_read_and_write_by_toolset(self) -> None:
        readonly = PermissionsFactory().create(agent(toolsets=("scoped_read_tools",)))
        writer = PermissionsFactory().create(agent(toolsets=("write",)))

        self.assertEqual([(permission.operations, permission.mode) for permission in readonly], [(["read"], "allow"), (["write"], "deny")])
        self.assertEqual([(permission.operations, permission.mode) for permission in writer], [(["read"], "deny"), (["write"], "allow")])

        with tempfile.TemporaryDirectory() as tmp:
            launch_cwd = Path(tmp) / "repo"
            (launch_cwd / ".agents" / "skills" / "project").mkdir(parents=True)
            (launch_cwd / ".agents" / "skills" / "project" / "SKILL.md").write_text("project", encoding="utf-8")
            team_config = team(working_directory=launch_cwd, load_cwd=launch_cwd)
            skill_agent = agent("entry", skills={"only": ["project"]})

            skill_permissions = PermissionsFactory(
                SkillSourceResolver(RuntimeConfiguration({"CODEX_HOME": ""}))
            ).create(skill_agent, team_config)

        self.assertEqual(
            [(permission.operations, permission.paths, permission.mode) for permission in skill_permissions],
            [
                (["read"], ["/skills/entry/project/project", "/skills/entry/project/project/**"], "allow"),
                (["read"], ["/**"], "deny"),
                (["write"], ["/**"], "deny"),
            ],
        )

    def test_tool_visibility_factory_maps_capabilities_to_deepagents_builtin_exclusions(self) -> None:
        factory = ToolVisibilityFactory(RuntimeConfiguration({"CODEX_HOME": ""}))
        with tempfile.TemporaryDirectory() as tmp:
            empty_team = team(working_directory=tmp, load_cwd=tmp)

            self.assertEqual(
                factory.excluded_tools(empty_team, agent(), task_available=False),
                frozenset(
                    {
                        "ls",
                        "read_file",
                        "glob",
                        "grep",
                        "write_file",
                        "edit_file",
                        "execute",
                        "task",
                    }
                ),
            )
        self.assertIsInstance(
            factory.create(empty_team, agent(), task_available=False),
            DeepAgentToolVisibilityMiddleware,
        )
        with tempfile.TemporaryDirectory() as tmp:
            launch_cwd = Path(tmp) / "repo"
            (launch_cwd / ".agents" / "skills" / "project").mkdir(parents=True)
            (launch_cwd / ".agents" / "skills" / "project" / "SKILL.md").write_text("project", encoding="utf-8")
            skill_team = team(working_directory=launch_cwd, load_cwd=launch_cwd)
            skill_exclusions = factory.excluded_tools(skill_team, agent("entry"), task_available=False)

        self.assertNotIn("read_file", skill_exclusions)
        self.assertIn("ls", skill_exclusions)
        self.assertEqual(
            factory.excluded_tools(
                team(team_defaults=defaults(execution_backend_default="local")),
                agent(toolsets=("scoped_read_tools", "write", "shell")),
                task_available=True,
            ),
            frozenset(),
        )
        self.assertIn(
            "execute",
            factory.excluded_tools(
                team(team_defaults=defaults(execution_backend_default="none")),
                agent(toolsets=("shell",)),
                task_available=True,
            ),
        )
        self.assertNotIn(
            "execute",
            ToolVisibilityFactory(RuntimeConfiguration({"EXECUTION_BACKEND": "local", "CODEX_HOME": ""})).excluded_tools(
                team(team_defaults=defaults(execution_backend_env="EXECUTION_BACKEND")),
                agent(toolsets=("shell",)),
                task_available=True,
            ),
        )

    def test_deep_agent_tool_visibility_middleware_filters_only_excluded_tools(self) -> None:
        middleware = DeepAgentToolVisibilityMiddleware(
            excluded_tools=frozenset({"read_file", "grep"})
        )
        read_tool = SimpleNamespace(name="read_file")
        custom_tool = SimpleNamespace(name="custom_lookup")
        request = FakeModelRequest(
            [
                read_tool,
                custom_tool,
                {"function": {"name": "grep"}},
                {"name": "custom_dict"},
            ]
        )

        visible_tools = middleware.wrap_model_call(request, lambda visible_request: visible_request.tools)

        self.assertEqual(visible_tools, [custom_tool, {"name": "custom_dict"}])
        async_visible_tools = asyncio.run(middleware.awrap_model_call(request, lambda visible_request: _async_value(visible_request.tools)))

        self.assertEqual(async_visible_tools, [custom_tool, {"name": "custom_dict"}])
        self.assertIsNone(middleware._tool_name({"function": {"name": object()}}))
        self.assertIsNone(middleware._tool_name({"bad": "shape"}))

    def test_graph_invocation_runs_async_graphs_inside_existing_event_loop(self) -> None:
        class SyncGraph:
            def invoke(self, value, *, config=None, **kwargs):
                return {"value": value, "config": config, "kwargs": kwargs}

        class AsyncGraph:
            async def ainvoke(self, value, *, config=None, **kwargs):
                return {"value": value, "config": config, "kwargs": kwargs}

        class FailingAsyncGraph:
            async def ainvoke(self, _value, *, config=None, **kwargs):
                raise RuntimeError("graph failed")

        async def run_success():
            return invoke_graph_sync(AsyncGraph(), "payload", config={"thread": "id"}, extra=True)

        async def run_failure():
            with self.assertRaisesRegex(RuntimeError, "graph failed"):
                invoke_graph_sync(FailingAsyncGraph(), "payload")

        self.assertEqual(invoke_graph_sync(SyncGraph(), "sync"), {"value": "sync", "config": None, "kwargs": {}})
        self.assertEqual(
            invoke_graph_sync(AsyncGraph(), "outside-loop"),
            {"value": "outside-loop", "config": None, "kwargs": {}},
        )
        self.assertEqual(
            asyncio.run(run_success()),
            {"value": "payload", "config": {"thread": "id"}, "kwargs": {"extra": True}},
        )
        asyncio.run(run_failure())

    def test_graph_invocation_requires_ainvoke_when_async_runner_is_supplied(self) -> None:
        class AsyncGraph:
            async def ainvoke(self, value, *, config=None, **kwargs):
                return {"value": value, "config": config, "kwargs": kwargs}

        class Runner:
            def run(self, coroutine_factory):
                return asyncio.run(coroutine_factory())

        self.assertEqual(
            invoke_graph_sync(AsyncGraph(), "payload", config={"thread": "id"}, async_runner=Runner(), extra=True),
            {"value": "payload", "config": {"thread": "id"}, "kwargs": {"extra": True}},
        )

        with self.assertRaisesRegex(TypeError, "ainvoke"):
            invoke_graph_sync(SimpleNamespace(), "payload", async_runner=object())

    def test_async_checkpointer_loop_guards_and_closes_failed_sqlite_connection(self) -> None:
        class FakeConnection:
            def __init__(self) -> None:
                self.closed = False

            async def execute(self, _statement: str) -> None:
                raise RuntimeError("setup failed")

            async def commit(self) -> None:
                raise AssertionError("commit should not run after failed execute")

            async def close(self) -> None:
                self.closed = True

        async def connect(_path: str) -> FakeConnection:
            return connection

        connection = FakeConnection()
        starter = AsyncCheckpointerLoop.__new__(AsyncCheckpointerLoop)
        starter.run = lambda coroutine_factory: asyncio.run(coroutine_factory())

        with patch("src.team_instanciator.runtime.async_checkpointer_loop.aiosqlite.connect", connect):
            with self.assertRaisesRegex(RuntimeError, "setup failed"):
                starter.start_sqlite(Path("checkpoints.sqlite"))

        self.assertTrue(connection.closed)

        stopped = AsyncCheckpointerLoop.__new__(AsyncCheckpointerLoop)
        stopped._loop = None
        stopped._thread = SimpleNamespace(ident=None)
        with self.assertRaisesRegex(RuntimeError, "not running"):
            stopped.run(lambda: _async_value("ignored"))
        stopped.close()

        owning_thread = AsyncCheckpointerLoop.__new__(AsyncCheckpointerLoop)
        owning_thread._loop = SimpleNamespace(is_running=lambda: True)
        owning_thread._thread = SimpleNamespace(ident=threading.get_ident())
        with self.assertRaisesRegex(RuntimeError, "owning thread"):
            owning_thread.run(lambda: _async_value("ignored"))

    def test_branch_thread_resolver_handles_fallbacks_and_thread_id_parsing(self) -> None:
        resolver_without_connection = BranchThreadResolver(None, "team")
        thread_factory = ThreadIdFactory()
        root_thread_id = thread_factory.root(team_id="team", conversation_id="thread")
        main_thread_id = thread_factory.mention(thread_factory.branch(root_thread_id, "branch_main"), "agent")

        self.assertEqual(
            resolver_without_connection.resolve(
                parent_physical_thread_id=main_thread_id,
                branch_id="branch_main",
                logical_thread_key="mention:agent",
                target_physical_thread_id="target",
            ),
            "target",
        )

        with sqlite3.connect(":memory:") as connection:
            resolver = BranchThreadResolver(connection, "team", thread_factory)
            resolved = resolver.resolve(
                parent_physical_thread_id=main_thread_id,
                branch_id="branch_main",
                logical_thread_key="mention:agent",
                target_physical_thread_id=main_thread_id,
            )

            self.assertEqual(resolved, main_thread_id)
            self.assertEqual(resolver._conversation_id(main_thread_id), "thread")

    def test_working_directory_runtime_lane_manifest_and_thread_ids(self) -> None:
        absolute = Path.cwd()
        resolver = WorkingDirectoryResolver()
        self.assertEqual(resolver.resolve_team(team(working_directory=absolute)), absolute)
        self.assertEqual(
            resolver.resolve_team(team(working_directory="relative-root")),
            Path("relative-root").resolve(),
        )
        self.assertEqual(
            resolver.resolve_agent(
                team(working_directory=absolute, agents={"entry": agent("entry", relative_working_directory=".")}),
                agent("entry", relative_working_directory="."),
            ),
            absolute,
        )
        with self.assertRaises(ValueError):
            resolver.resolve_agent(
                team(working_directory=absolute),
                agent("entry", relative_working_directory=str(absolute)),
            )

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
        root_thread_id = thread_factory.root(team_id="team", conversation_id="thread")
        mention_thread_id = thread_factory.mention(thread_factory.branch(root_thread_id, "branch_01"), "agent")
        relation_thread_id = thread_factory.relation(mention_thread_id, relation_config)

        self.assertEqual(entrypoint_lane.thread_id("root"), "root")
        self.assertIsNone(RuntimeLane("task", "task-subagent-type", "worker", "Worker").thread_id("root"))
        self.assertEqual(relation_lane.to_dict("root")["thread_id"], "root:relation:rel_worker:agent:worker")
        self.assertEqual(manifest.lanes_for("root")[0]["thread_id"], "root")
        self.assertEqual(manifest.to_dict()["team_id"], "team")
        self.assertEqual(thread_factory.root(team_id="team", conversation_id="thread"), "ca:v1:team:team:conversation:thread")
        self.assertEqual(relation_thread_id, f"{mention_thread_id}:relation:rel_worker:agent:worker")
        self.assertEqual(thread_factory.relation_pattern(relation_config), "{parent_logical_key}:relation:rel_worker:agent:worker")
        self.assertEqual(
            thread_factory.relation_id(SimpleNamespace(source="entry", relation="review", target="worker", id="")),
            "entry:review:worker",
        )
        self.assertEqual(thread_factory.branch_id_from_thread_id(mention_thread_id), "branch_01")
        self.assertEqual(thread_factory.logical_thread_key(mention_thread_id), "mention:agent")
        self.assertEqual(
            thread_factory.logical_thread_key(relation_thread_id),
            "mention:agent:relation:rel_worker:agent:worker",
        )
        parsed = thread_factory.parse_relation_thread_id(relation_thread_id)
        self.assertIsNotNone(parsed)
        self.assertEqual(parsed.relation_id, "rel_worker")
        self.assertEqual(parsed.target_agent_id, "worker")
        self.assertEqual(thread_factory.mention(root_thread_id, "architect"), f"{root_thread_id}:mention:architect")
        self.assertEqual(thread_factory.mention_pattern("architect"), "mention:architect")
        self.assertEqual(thread_factory.parse(root_thread_id).version, "v1")
        with self.assertRaisesRegex(ValueError, "mention thread"):
            thread_factory.logical_thread_key(root_thread_id)
        with self.assertRaisesRegex(ValueError, "Unsupported thread id version: v2"):
            thread_factory.parse("ca:v2:team:team:conversation:thread")
        with self.assertRaisesRegex(ValueError, "Invalid thread id"):
            thread_factory.parse("v1:team:team:conversation:thread")
        self.assertIsNone(thread_factory.parse_relation_thread_id(mention_thread_id))
        self.assertIsNone(thread_factory.parse_relation_thread_id("root:entry:ask_worker:worker"))
        self.assertIsNone(thread_factory.parse_relation_thread_id("bad"))
        self.assertIsNone(thread_factory.parse_relation_thread_id("root:entry::worker"))
        for invalid_thread_id in (
            "ca:v1:team:team",
            f"{root_thread_id}:topic:branch_main",
            f"{root_thread_id}:branch:branch_main:agent:entry",
            f"{mention_thread_id}:relation:rel_worker:target:worker",
        ):
            with self.assertRaisesRegex(ValueError, "Invalid thread id"):
                thread_factory.parse(invalid_thread_id)

    def test_thread_id_factory_dispatches_to_registered_version_codecs(self) -> None:
        class V2Codec(ThreadIdV1Codec):
            @property
            def version(self) -> str:
                return "v2"

        v1 = ThreadIdV1Codec()
        v2 = V2Codec()
        thread_factory = ThreadIdFactory(writer=v1, parsers=(v1, v2))
        root_thread_id = "ca:v2:team:team:conversation:thread"

        self.assertEqual(thread_factory.parse(root_thread_id).version, "v2")
        self.assertEqual(
            thread_factory.branch(root_thread_id, "branch_main"),
            "ca:v2:team:team:conversation:thread:branch:branch_main",
        )

    def test_skills_resolver_returns_source_roots_and_legacy_lists_filter_catalog(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            launch_cwd = Path(tmp) / "repo"
            team_dir = launch_cwd / "teams" / "software"
            home = Path(tmp) / "codex-home"
            (launch_cwd / ".agents" / "skills" / "project").mkdir(parents=True)
            (launch_cwd / ".agents" / "skills" / "project" / "SKILL.md").write_text("project", encoding="utf-8")
            (team_dir / "skills" / "team").mkdir(parents=True)
            (team_dir / "skills" / "team" / "SKILL.md").write_text("team", encoding="utf-8")
            (home / "skills" / "user").mkdir(parents=True)
            (home / "skills" / "user" / "SKILL.md").write_text("user", encoding="utf-8")
            resolver = SkillsResolver(RuntimeConfiguration({"CODEX_HOME": str(home)}))
            team_config = team(working_directory=launch_cwd, load_cwd=launch_cwd, path=team_dir / "team.yaml")

            self.assertIsNone(resolver.resolve(team_config, agent(skills=None)))
            self.assertEqual(
                resolver.resolve(team_config, agent("entry", skills="inherit")),
                [
                    ("/skills/user", "User"),
                    ("/skills/project", "Project"),
                    ("/skills/team", "Team"),
                ],
            )
            self.assertEqual(
                SkillSourceResolver(RuntimeConfiguration({"CODEX_HOME": str(home)})).read_permission_paths(
                    team_config,
                    agent("entry", skills="inherit"),
                ),
                [
                    "/skills/user",
                    "/skills/user/**",
                    "/skills/project",
                    "/skills/project/**",
                    "/skills/team",
                    "/skills/team/**",
                ],
            )
            self.assertIsNone(resolver.resolve(team_config, agent(skills="none")))

            resolved = resolver.resolve(team_config, agent("entry", skills=["project", "team", object()]))

        self.assertEqual(
            resolved,
            [
                ("/skills/entry/project", "Project"),
                ("/skills/entry/team", "Team"),
            ],
        )

    def test_skills_resolver_rejects_unknown_selected_skill_ids(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            launch_cwd = Path(tmp) / "repo"
            (launch_cwd / ".agents" / "skills" / "project").mkdir(parents=True)
            (launch_cwd / ".agents" / "skills" / "project" / "SKILL.md").write_text("project", encoding="utf-8")

            with self.assertRaisesRegex(TeamInstanciatorError, "unknown skill id 'missing'"):
                SkillsResolver(RuntimeConfiguration({"CODEX_HOME": ""})).resolve(
                    team(working_directory=launch_cwd, load_cwd=launch_cwd),
                    agent("entry", skills={"only": ["missing"]}),
                )

    def test_skill_source_resolver_collapses_duplicates_and_warns_for_missing_configured_sources(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            team_dir = root / "teams" / "software"
            (team_dir / "skills" / "implicit").mkdir(parents=True)
            (team_dir / "skills" / "implicit" / "SKILL.md").write_text("implicit", encoding="utf-8")
            (team_dir / "extra" / "extra").mkdir(parents=True)
            (team_dir / "extra" / "extra" / "SKILL.md").write_text("extra", encoding="utf-8")
            resolver = SkillSourceResolver(RuntimeConfiguration({"CODEX_HOME": ""}))
            absolute_source = team_dir / "absolute"
            (absolute_source / "absolute").mkdir(parents=True)
            (absolute_source / "absolute" / "SKILL.md").write_text("absolute", encoding="utf-8")
            team_config = team(
                working_directory=root,
                load_cwd=root,
                path=team_dir / "team.yaml",
                skill_sources=("skills", "missing", "extra", str(absolute_source)),
            )

            with self.assertLogs("src.team_instanciator.resolvers.skill_source_resolver", level="WARNING") as logs:
                sources = resolver.resolve_team_sources(team_config)

        self.assertEqual(
            [source.host_path for source in sources],
            [(team_dir / "skills").resolve(), (team_dir / "extra").resolve(), absolute_source.resolve()],
        )
        self.assertEqual([source.label for source in sources], ["Team Source 1", "Team Source 3", "Team Source 4"])
        self.assertIn("Configured skill source does not exist", logs.output[0])
        self.assertEqual(resolver._unique_virtual_path("/skills/project", {"/skills/project"}), "/skills/project-2")


if __name__ == "__main__":
    unittest.main()
