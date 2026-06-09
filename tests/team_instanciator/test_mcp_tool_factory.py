from __future__ import annotations

import os
import unittest
from datetime import timedelta
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from langchain_core.tools import StructuredTool

from src.team_instanciator.configuration.runtime_configuration import RuntimeConfiguration
from src.team_instanciator.errors.team_instanciator_error import TeamInstanciatorError
from src.team_instanciator.factories.mcp_tool_factory import McpToolFactory
from src.team_instanciator.tools.custom_tool_context import CustomToolContext
from src.team_instanciator.tools.env_view import EnvView
from src.team_loader.models.mcp_server_definition import McpConfigValue, McpServerDefinition
from tests.support import agent, team


AUTH_OBJECT = object()


def custom_auth_factory(context, args):
    return {"auth": args["audience"], "token": context.env.get("CUSTOM_TOKEN")}


def one_argument_auth_factory(context):
    return AUTH_OBJECT


def tool_named(name: str):
    def run() -> str:
        """Run fake MCP tool."""

        return name

    return StructuredTool.from_function(run, name=name)


class FakeClient:
    def __init__(self, tools):
        self._tools = tools

    async def get_tools(self):
        return self._tools


class FailingClient:
    async def get_tools(self):
        raise RuntimeError("network down")


class CapturingClientFactory:
    def __init__(self, tools) -> None:
        self.tools = tools
        self.connections: list[dict[str, dict[str, object]]] = []

    def __call__(self, connections: dict[str, dict[str, object]]) -> FakeClient:
        self.connections.append(connections)
        return FakeClient(self.tools)


class McpToolFactoryTests(unittest.TestCase):
    def test_http_config_resolves_headers_bearer_auth_default_timeout_and_all_tools(self) -> None:
        client_factory = CapturingClientFactory([tool_named("search_docs"), tool_named("fetch_doc")])
        factory = McpToolFactory(client_factory)
        definition = McpServerDefinition(
            id="docs",
            transport="streamable_http",
            command=None,
            args=(),
            url="https://mcp.example.test/mcp",
            env={},
            headers={
                "X-Client": McpConfigValue(value="coding-agents"),
                "X-Tenant": McpConfigValue(env="TENANT_ID"),
            },
            auth=SimpleNamespace(type="bearer", env="MCP_TOKEN", header=None, factory=None, args={}),
            timeout=None,
            cwd=None,
            exposes=None,
        )

        tools = factory.create(definition, self._context({"TENANT_ID": "tenant-1", "MCP_TOKEN": "secret"}))

        self.assertEqual([tool.name for tool in tools], ["search_docs", "fetch_doc"])
        connection = client_factory.connections[0]["docs"]
        self.assertEqual(connection["transport"], "streamable_http")
        self.assertEqual(connection["url"], "https://mcp.example.test/mcp")
        self.assertEqual(connection["timeout"], timedelta(seconds=30))
        self.assertEqual(
            connection["headers"],
            {
                "X-Client": "coding-agents",
                "X-Tenant": "tenant-1",
                "Authorization": "Bearer secret",
            },
        )

    def test_stdio_config_merges_env_and_explicit_exposes_are_cached(self) -> None:
        client_factory = CapturingClientFactory([tool_named("now"), tool_named("convert_time")])
        factory = McpToolFactory(client_factory)
        definition = McpServerDefinition(
            id="time",
            transport="stdio",
            command="uvx",
            args=("mcp-server-time",),
            url=None,
            env={
                "STATIC": McpConfigValue(value="fixed"),
                "RUNTIME": McpConfigValue(env="RUNTIME"),
            },
            headers={},
            auth=None,
            timeout=None,
            cwd=".",
            exposes=("now",),
        )

        with patch.dict(os.environ, {"KEEP": "yes", "RUNTIME": "process", "CONFIG": "process"}, clear=True):
            context = self._context({"RUNTIME": "runtime", "CONFIG": "config"})
            first = factory.create(definition, context)
            second = factory.create(definition, context)

        self.assertIs(first, second)
        self.assertEqual([tool.name for tool in first], ["now"])
        self.assertEqual(len(client_factory.connections), 1)
        connection = client_factory.connections[0]["time"]
        self.assertEqual(connection["transport"], "stdio")
        self.assertEqual(connection["command"], "uvx")
        self.assertEqual(connection["args"], ["mcp-server-time"])
        self.assertEqual(connection["cwd"], ".")
        self.assertEqual(connection["env"]["KEEP"], "yes")
        self.assertEqual(connection["env"]["CONFIG"], "config")
        self.assertEqual(connection["env"]["RUNTIME"], "runtime")
        self.assertEqual(connection["env"]["STATIC"], "fixed")

    def test_api_key_auth_sse_timeout_missing_exposes_and_missing_env_errors(self) -> None:
        client_factory = CapturingClientFactory([tool_named("one")])
        factory = McpToolFactory(client_factory)
        definition = McpServerDefinition(
            id="docs",
            transport="sse",
            command=None,
            args=(),
            url="https://mcp.example.test/sse",
            env={},
            headers={},
            auth=SimpleNamespace(type="api_key", env="MCP_API_KEY", header="X-API-Key", factory=None, args={}),
            timeout=12,
            cwd=None,
            exposes=("missing",),
        )

        with self.assertRaisesRegex(TeamInstanciatorError, "Missing required environment value"):
            factory.create(definition, self._context({}))

        with self.assertRaisesRegex(TeamInstanciatorError, "exposes mismatch"):
            factory.create(definition, self._context({"MCP_API_KEY": "key"}))

        connection = client_factory.connections[0]["docs"]
        self.assertEqual(connection["transport"], "sse")
        self.assertEqual(connection["timeout"], 12)
        self.assertEqual(connection["headers"], {"X-API-Key": "key"})

    def test_custom_auth_factory_signature_and_result(self) -> None:
        client_factory = CapturingClientFactory([tool_named("one")])
        factory = McpToolFactory(client_factory)
        definition = McpServerDefinition(
            id="docs",
            transport="streamable_http",
            command=None,
            args=(),
            url="https://mcp.example.test/mcp",
            env={},
            headers={},
            auth=SimpleNamespace(
                type="custom",
                env=None,
                header=None,
                factory=f"{__name__}:custom_auth_factory",
                args={"audience": "docs"},
            ),
            timeout=None,
            cwd=None,
            exposes=None,
        )

        factory.create(definition, self._context({"CUSTOM_TOKEN": "token"}))

        self.assertEqual(client_factory.connections[0]["docs"]["auth"], {"auth": "docs", "token": "token"})

        bad_definition = McpServerDefinition(
            id="bad",
            transport="streamable_http",
            command=None,
            args=(),
            url="https://mcp.example.test/mcp",
            env={},
            headers={},
            auth=SimpleNamespace(
                type="custom",
                env=None,
                header=None,
                factory=f"{__name__}:one_argument_auth_factory",
                args={},
            ),
            timeout=None,
            cwd=None,
            exposes=None,
        )
        with self.assertRaisesRegex(TeamInstanciatorError, "must accept"):
            factory.create(bad_definition, self._context({}))

    def test_reports_bad_client_and_non_tool_results(self) -> None:
        with self.assertRaisesRegex(TeamInstanciatorError, "get_tools"):
            McpToolFactory(lambda _connections: object()).create(self._stdio_definition(), self._context({}))

        with self.assertRaisesRegex(TeamInstanciatorError, "non-tool"):
            McpToolFactory(lambda _connections: FakeClient(["bad"])).create(self._stdio_definition(), self._context({}))

        with self.assertRaisesRegex(TeamInstanciatorError, "Could not load MCP tools from server 'time': network down"):
            McpToolFactory(lambda _connections: FailingClient()).create(self._stdio_definition(), self._context({}))

    def _stdio_definition(self) -> McpServerDefinition:
        return McpServerDefinition(
            id="time",
            transport="stdio",
            command="uvx",
            args=(),
            url=None,
            env={},
            headers={},
            auth=None,
            timeout=None,
            cwd=None,
            exposes=None,
        )

    def _context(self, values: dict[str, object]) -> CustomToolContext:
        configuration = RuntimeConfiguration(values)
        return CustomToolContext(
            root_dir=Path.cwd(),
            env=EnvView(configuration),
            runtime_config=configuration,
            agent_config=agent("entry"),
            team_config=team(),
            history=SimpleNamespace(),
        )


if __name__ == "__main__":
    unittest.main()
