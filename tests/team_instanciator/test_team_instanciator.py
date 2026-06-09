from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage
from langchain_core.outputs import ChatGeneration, ChatResult

from src.team_instanciator.configuration.runtime_configuration import RuntimeConfiguration
from src.team_instanciator.core.team_instanciator import TeamInstanciator
from tests.support import agent, defaults, team


class Loader:
    def __init__(self, loaded_team) -> None:
        self.loaded_team = loaded_team
        self.calls = []

    def load(self, team_file, variables):
        self.calls.append((team_file, variables))
        return self.loaded_team


class ClosableCheckpointer:
    def __init__(self) -> None:
        self.checkpointer = "checkpointer"
        self.connection = None
        self.closed = False

    def close(self) -> None:
        self.closed = True


class FakeCheckpointerFactory:
    handle = ClosableCheckpointer()

    def __init__(self, configuration) -> None:
        self.configuration = configuration

    def create(self, team_config):
        return self.__class__.handle


class FakeRegistry:
    graph_exception: Exception | None = None
    graph_calls: list[str] = []

    def __init__(self, *args) -> None:
        self.args = args

    def graph(self, agent_id: str):
        self.__class__.graph_calls.append(agent_id)
        if self.__class__.graph_exception is not None:
            raise self.__class__.graph_exception
        return SimpleNamespace(id=f"graph:{agent_id}")


class ToolCaptureChatModel(BaseChatModel):
    def __init__(self) -> None:
        super().__init__()
        object.__setattr__(self, "bound_tool_names", [])

    @property
    def _llm_type(self) -> str:
        return "tool-capture"

    def bind_tools(self, tools, *, tool_choice=None, **kwargs):
        self.bound_tool_names.append([self._tool_name(tool) for tool in tools])
        return self

    def _generate(self, messages, stop=None, run_manager=None, **kwargs):
        return ChatResult(generations=[ChatGeneration(message=AIMessage(content="done"))])

    def _tool_name(self, tool: object) -> str | None:
        if isinstance(tool, dict):
            name = tool.get("name")
            if isinstance(name, str):
                return name
            function = tool.get("function")
            if isinstance(function, dict):
                function_name = function.get("name")
                return function_name if isinstance(function_name, str) else None
            return None
        name = getattr(tool, "name", None)
        return name if isinstance(name, str) else None


class TeamInstanciatorTests(unittest.TestCase):
    def setUp(self) -> None:
        FakeCheckpointerFactory.handle = ClosableCheckpointer()
        FakeRegistry.graph_exception = None
        FakeRegistry.graph_calls = []

    def test_instantiate_builds_entrypoint_graph_and_runtime_manifest(self) -> None:
        loaded_team = team(
            team_id="product",
            agents={"entry": agent("entry", entrypoint=True)},
            working_directory=Path.cwd(),
        )
        loader = Loader(loaded_team)

        with (
            patch("src.team_instanciator.core.team_instanciator.CheckpointerFactory", FakeCheckpointerFactory),
            patch("src.team_instanciator.core.team_instanciator.AgentGraphRegistry", FakeRegistry),
        ):
            instantiated = TeamInstanciator(loader, config_variables={"BASE": "one"}).instantiate("team.yaml", {"topic": "ai"}, {"EXTRA": "two"})

        self.assertEqual(loader.calls, [("team.yaml", {"topic": "ai"})])
        self.assertEqual(FakeRegistry.graph_calls, ["entry"])
        self.assertEqual(instantiated.team, loaded_team)
        self.assertEqual(instantiated.graph.id, "graph:entry")
        self.assertFalse(FakeCheckpointerFactory.handle.closed)
        self.assertEqual(instantiated.runtime_manifest.team_id, "product")

    def test_instantiate_closes_checkpointer_when_team_has_no_entrypoint(self) -> None:
        loaded_team = team(agents={"worker": agent("worker")}, working_directory=Path.cwd())

        with (
            patch("src.team_instanciator.core.team_instanciator.CheckpointerFactory", FakeCheckpointerFactory),
            patch("src.team_instanciator.core.team_instanciator.AgentGraphRegistry", FakeRegistry),
            self.assertRaisesRegex(ValueError, "no entrypoint"),
        ):
            TeamInstanciator(Loader(loaded_team)).instantiate("team.yaml")

        self.assertTrue(FakeCheckpointerFactory.handle.closed)

    def test_instantiate_closes_checkpointer_when_graph_creation_fails(self) -> None:
        loaded_team = team(agents={"entry": agent("entry", entrypoint=True)}, working_directory=Path.cwd())
        FakeRegistry.graph_exception = RuntimeError("boom")

        with (
            patch("src.team_instanciator.core.team_instanciator.CheckpointerFactory", FakeCheckpointerFactory),
            patch("src.team_instanciator.core.team_instanciator.AgentGraphRegistry", FakeRegistry),
            self.assertRaisesRegex(RuntimeError, "boom"),
        ):
            TeamInstanciator(Loader(loaded_team)).instantiate("team.yaml")

        self.assertTrue(FakeCheckpointerFactory.handle.closed)

    def test_runtime_configuration_instance_is_reused(self) -> None:
        configuration = RuntimeConfiguration({"VALUE": "one"})

        instanciator = TeamInstanciator(config_variables=configuration)

        self.assertIs(instanciator._configuration, configuration)

    def test_yaml_instantiation_binds_only_configured_web_tools_to_model(self) -> None:
        bound_tool_names = self._model_bound_tools(
            agent_frontmatter="\n".join(
                [
                    "---",
                    "name: Entry",
                    "toolsets:",
                    "  - web",
                    "---",
                ]
            ),
            team_toolsets=[
                "toolsets:",
                "  web:",
                "    - web_search",
                "    - fetch_url",
            ],
        )

        self.assertEqual(bound_tool_names, {"write_todos", "web_search", "fetch_url"})

    def test_yaml_instantiation_binds_read_tools_only_with_scoped_read_tools(self) -> None:
        bound_tool_names = self._model_bound_tools(
            agent_frontmatter="\n".join(
                [
                    "---",
                    "name: Entry",
                    "toolsets:",
                    "  - scoped_read_tools",
                    "---",
                ]
            ),
            team_toolsets=[
                "toolsets:",
                "  scoped_read_tools:",
                "    - ls",
                "    - read_file",
                "    - glob",
                "    - grep",
            ],
        )

        self.assertEqual(bound_tool_names, {"write_todos", "ls", "read_file", "glob", "grep"})

    def _model_bound_tools(self, *, agent_frontmatter: str, team_toolsets: list[str]) -> set[str]:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            agents_dir = root / "agents"
            agents_dir.mkdir()
            (agents_dir / "entry.mdc").write_text(f"{agent_frontmatter}\nPrompt", encoding="utf-8")
            team_file = root / "team.yaml"
            team_file.write_text(
                "\n".join(
                    [
                        "schema_version: 1",
                        "id: product",
                        "working_directory: .",
                        "defaults:",
                        "  model:",
                        "    default: openai:gpt-tool-visibility-test",
                        "  checkpointer:",
                        "    default: memory",
                        "  execution_backend:",
                        "    default: none",
                        *team_toolsets,
                        "agents:",
                        "  Entry:",
                        "    kind: deepagent",
                        "    config: agents/entry.mdc",
                        "    entrypoint: true",
                    ]
                ),
                encoding="utf-8",
            )
            model = ToolCaptureChatModel()

            with patch("src.team_instanciator.resolvers.model_resolver.init_chat_model", return_value=model):
                instantiated = TeamInstanciator().instantiate(team_file)
                try:
                    instantiated.invoke(
                        {"messages": [{"role": "user", "content": "hello"}]},
                        config={"configurable": {"thread_id": "test-thread"}},
                    )
                finally:
                    instantiated.close()

        self.assertEqual(len(model.bound_tool_names), 1)
        names = model.bound_tool_names[0]
        self.assertEqual(len(names), len(set(names)))
        return {name for name in names if name is not None}


if __name__ == "__main__":
    unittest.main()
