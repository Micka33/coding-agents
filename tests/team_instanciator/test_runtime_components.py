from __future__ import annotations

import asyncio
import sqlite3
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from src.team_instanciator.resolvers.agent_runtime_resolver import AgentRuntimeResolver
from src.team_instanciator.resolvers.memory_resolver import MemoryResolver
from src.team_instanciator.factories.permissions_factory import PermissionsFactory
from src.team_instanciator.factories.tool_visibility_factory import ToolVisibilityFactory
from src.team_loader.resolvers.working_directory_resolver import WorkingDirectoryResolver
from src.team_instanciator.configuration.runtime_configuration import RuntimeConfiguration
from src.team_instanciator.runtime.runtime_lane import RuntimeLane
from src.team_instanciator.runtime.branch_thread_resolver import BranchThreadResolver
from src.team_instanciator.runtime.graph_invocation import invoke_graph_sync
from src.team_instanciator.resolvers.skills_resolver import SkillsResolver
from src.team_instanciator.errors.team_instanciator_error import TeamInstanciatorError
from src.team_instanciator.manifest.team_runtime_manifest import TeamRuntimeManifest
from src.team_instanciator.runtime.thread_id_factory import ThreadIdFactory
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

    def test_tool_visibility_factory_maps_capabilities_to_deepagents_builtin_exclusions(self) -> None:
        factory = ToolVisibilityFactory()

        self.assertEqual(
            factory.excluded_tools(team(), agent(), task_available=False),
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
            factory.create(team(), agent(), task_available=False),
            DeepAgentToolVisibilityMiddleware,
        )
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
            ToolVisibilityFactory(RuntimeConfiguration({"EXECUTION_BACKEND": "local"})).excluded_tools(
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

    def test_branch_thread_resolver_handles_fallbacks_and_thread_id_parsing(self) -> None:
        resolver_without_connection = BranchThreadResolver(None, "team")

        self.assertEqual(
            resolver_without_connection.resolve(
                parent_physical_thread_id="thread:branch:branch_main:mention:agent",
                branch_id="branch_main",
                logical_thread_key="mention:agent",
                target_physical_thread_id="target",
            ),
            "target",
        )

        with sqlite3.connect(":memory:") as connection:
            resolver = BranchThreadResolver(connection, "team")
            resolved = resolver.resolve(
                parent_physical_thread_id="thread:mention:agent",
                branch_id="branch_main",
                logical_thread_key="mention:agent",
                target_physical_thread_id="thread:branch:branch_main:mention:agent",
            )

            self.assertEqual(resolved, "thread:branch:branch_main:mention:agent")
            self.assertEqual(resolver._conversation_id("thread:branch:branch_main:mention:agent"), "thread")
            self.assertEqual(resolver._conversation_id("thread:mention:agent"), "thread")
            self.assertEqual(resolver._conversation_id("thread:relation:worker"), "thread")
            self.assertEqual(resolver._conversation_id("thread"), "thread")

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

        self.assertEqual(entrypoint_lane.thread_id("root"), "root")
        self.assertIsNone(RuntimeLane("task", "task-subagent-type", "worker", "Worker").thread_id("root"))
        self.assertEqual(relation_lane.to_dict("root")["thread_id"], "root:relation:rel_worker:agent:worker")
        self.assertEqual(manifest.lanes_for("root")[0]["thread_id"], "root")
        self.assertEqual(manifest.to_dict()["team_id"], "team")
        self.assertEqual(thread_factory.root("team"), "team")
        self.assertEqual(thread_factory.relation("root", relation_config), "root:relation:rel_worker:agent:worker")
        self.assertEqual(thread_factory.relation_pattern(relation_config), "{parent_thread_id}:relation:rel_worker:agent:worker")
        self.assertEqual(
            thread_factory.relation_id(SimpleNamespace(source="entry", relation="review", target="worker", id="")),
            "entry:review:worker",
        )
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
            launch_cwd = Path(tmp) / "repo"
            working = launch_cwd / "workspace"
            home = Path(tmp) / "codex-home"
            (launch_cwd / ".agents" / "skills" / "project").mkdir(parents=True)
            (launch_cwd / ".agents" / "skills" / "project" / "SKILL.md").write_text("project", encoding="utf-8")
            (working / ".agents" / "skills" / "wrong").mkdir(parents=True)
            (working / ".agents" / "skills" / "wrong" / "SKILL.md").write_text("wrong", encoding="utf-8")
            (home / "skills" / "user").mkdir(parents=True)
            (home / "skills" / "user" / "SKILL.md").write_text("user", encoding="utf-8")
            resolver = SkillsResolver(RuntimeConfiguration({"CODEX_HOME": str(home)}))
            team_config = team(working_directory="workspace", load_cwd=launch_cwd)

            self.assertIsNone(resolver.resolve(team_config, agent(skills=None)))
            self.assertIsNone(resolver.resolve(team_config, agent(skills="inherit")))
            self.assertIsNone(resolver.resolve(team_config, agent(skills="none")))
            self.assertIsNone(resolver.resolve(team_config, agent(skills="project")))

            resolved = resolver.resolve(team_config, agent(skills=["project", "user", "missing", "wrong", object()]))

        self.assertEqual(
            resolved,
            [
                str(launch_cwd.resolve() / ".agents" / "skills" / "project"),
                str(home / "skills" / "user"),
                str(launch_cwd.resolve() / ".agents" / "skills" / "missing"),
                str(launch_cwd.resolve() / ".agents" / "skills" / "wrong"),
            ],
        )


if __name__ == "__main__":
    unittest.main()
