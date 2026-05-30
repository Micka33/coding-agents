from __future__ import annotations

import unittest
from types import SimpleNamespace

from langchain_core.tools import StructuredTool

from src.team_instanciator.toolset_resolver import ToolsetResolver
from tests.support import agent, defaults, team


def tool_named(name: str):
    def run() -> str:
        """Run the fake tool."""

        return name

    return StructuredTool.from_function(run, name=name)


class CustomFactory:
    def create(self, definition, context):
        return [tool_named("ls"), tool_named("custom_tool")]


class BuiltinFactory:
    def __init__(self) -> None:
        self.names: list[str] = []

    def create(self, name, root_dir):
        self.names.append(name)
        return tool_named(name)


class ToolsetResolverTests(unittest.TestCase):
    def test_deepagents_resolution_filters_deepagents_builtins_but_keeps_self_contained_tools(self) -> None:
        resolver = ToolsetResolver()
        resolver._custom_factory = CustomFactory()
        resolver._builtin_factory = BuiltinFactory()
        team_config = team(
            team_defaults=defaults(root_dir="."),
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


if __name__ == "__main__":
    unittest.main()
