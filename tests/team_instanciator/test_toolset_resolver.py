from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from langchain_core.tools import StructuredTool

from src.team_instanciator.errors.team_instanciator_error import TeamInstanciatorError
from src.team_instanciator.factories.tool_name_validator import ToolNameValidator
from src.team_instanciator.resolvers.toolset_resolver import ToolsetResolver
from tests.support import agent, team


def tool_named(name: str):
    def run() -> str:
        """Run the fake tool."""

        return name

    return StructuredTool.from_function(run, name=name)


class CustomFactory:
    def create(self, definition, context):
        return [tool_named("ls"), tool_named("custom_tool")]


class McpFactory:
    def __init__(self) -> None:
        self.calls = 0

    def create(self, definition, context):
        self.calls += 1
        return [tool_named("ls"), tool_named("mcp_tool")]


class BuiltinFactory:
    def __init__(self) -> None:
        self.names: list[str] = []
        self.root_dirs: list[Path] = []

    def create(self, name, root_dir):
        self.names.append(name)
        self.root_dirs.append(root_dir)
        return tool_named(name)


class ToolsetResolverTests(unittest.TestCase):
    def test_deepagents_resolution_filters_deepagents_builtins_but_keeps_self_contained_tools(self) -> None:
        resolver = ToolsetResolver()
        resolver._custom_factory = CustomFactory()
        resolver._builtin_factory = BuiltinFactory()
        team_config = team(
            custom_tools={"probe": object()},
            toolsets={
                "mixed": SimpleNamespace(
                    tools=(
                        SimpleNamespace(name="ls", custom=None),
                        SimpleNamespace(name="web_search", custom=None),
                        SimpleNamespace(name=None, custom="probe"),
                    )
                )
            },
        )

        deepagents_tools = resolver.resolve_for_deepagents(team_config, agent(toolsets=("mixed",)))
        langchain_tools = resolver.resolve_for_langchain(team_config, agent(toolsets=("mixed",)))

        self.assertEqual([tool.name for tool in deepagents_tools], ["web_search", "custom_tool"])
        self.assertEqual([tool.name for tool in langchain_tools], ["ls", "web_search", "ls", "custom_tool"])

    def test_mcp_resolution_filters_deepagents_builtins(self) -> None:
        resolver = ToolsetResolver()
        mcp_factory = McpFactory()
        resolver._mcp_factory = mcp_factory
        team_config = team(
            mcp_servers={"probe": object()},
            toolsets={
                "mcp": SimpleNamespace(
                    tools=(
                        SimpleNamespace(name=None, custom=None, mcp="probe"),
                        SimpleNamespace(name=None, custom=None, mcp="probe"),
                    )
                )
            },
        )

        deepagents_tools = resolver.resolve_for_deepagents(team_config, agent(toolsets=("mcp",)))
        langchain_tools = resolver.resolve_for_langchain(team_config, agent(toolsets=("mcp",)))

        self.assertEqual([tool.name for tool in deepagents_tools], ["mcp_tool", "mcp_tool"])
        self.assertEqual([tool.name for tool in langchain_tools], ["ls", "mcp_tool", "ls", "mcp_tool"])
        self.assertEqual(mcp_factory.calls, 4)

    def test_tool_name_validator_rejects_duplicate_named_tools(self) -> None:
        with self.assertRaisesRegex(TeamInstanciatorError, "duplicate tool names: one"):
            ToolNameValidator().validate_unique("entry", [tool_named("one"), tool_named("one")])

    def test_builtin_tools_use_agent_working_directory(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            agent_dir = root / "packages" / "api"
            agent_dir.mkdir(parents=True)
            builtin_factory = BuiltinFactory()
            resolver = ToolsetResolver()
            resolver._builtin_factory = builtin_factory
            team_config = team(
                working_directory=root,
                toolsets={"write": SimpleNamespace(tools=(SimpleNamespace(name="write_file", custom=None),))},
            )

            resolver.resolve_for_langchain(
                team_config,
                agent(toolsets=("write",), relative_working_directory="packages/api"),
            )

        self.assertEqual(builtin_factory.root_dirs, [agent_dir.resolve()])


if __name__ == "__main__":
    unittest.main()
