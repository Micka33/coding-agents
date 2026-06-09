from __future__ import annotations

import importlib
import inspect
import os
from collections.abc import Callable, Sequence
from datetime import timedelta
from typing import Any, cast

from langchain_core.tools import BaseTool

from src.type_defs import JsonObject
from src.team_loader.models.mcp_server_definition import McpConfigValue, McpServerDefinition

from src.team_instanciator.errors.team_instanciator_error import TeamInstanciatorError
from src.team_instanciator.runtime.graph_invocation import _run_coroutine_sync
from src.team_instanciator.tools.custom_tool_context import CustomToolContext

McpAuthFactoryCallable = Callable[[CustomToolContext, JsonObject], object]
McpClientFactoryCallable = Callable[[dict[str, dict[str, Any]]], object]


class McpToolFactory:
    DEFAULT_TIMEOUT_SECONDS = 30

    def __init__(self, client_factory: McpClientFactoryCallable | None = None) -> None:
        self._client_factory = client_factory or self._default_client
        self._cache: dict[str, list[BaseTool]] = {}

    def create(self, definition: McpServerDefinition, context: CustomToolContext) -> list[BaseTool]:
        if definition.id not in self._cache:
            tools = self._load_tools(definition, context)
            self._cache[definition.id] = self._filter_exposed_tools(definition, tools)
        return self._cache[definition.id]

    def _load_tools(self, definition: McpServerDefinition, context: CustomToolContext) -> list[BaseTool]:
        try:
            client = self._client_factory({definition.id: self._connection_config(definition, context)})
            get_tools = getattr(client, "get_tools", None)
            if not callable(get_tools):
                raise TeamInstanciatorError("MCP client must expose get_tools().")
            result = _run_coroutine_sync(get_tools())
            return self._normalize_tools(definition, result)
        except TeamInstanciatorError:
            raise
        except Exception as error:
            raise TeamInstanciatorError(f"Could not load MCP tools from server '{definition.id}': {error}") from error

    def _connection_config(self, definition: McpServerDefinition, context: CustomToolContext) -> dict[str, Any]:
        if definition.transport == "stdio":
            return self._stdio_config(definition, context)
        if definition.transport in {"streamable_http", "sse"}:
            return self._http_config(definition, context)
        raise TeamInstanciatorError(f"Unsupported MCP transport: {definition.transport}")

    def _stdio_config(self, definition: McpServerDefinition, context: CustomToolContext) -> dict[str, Any]:
        config: dict[str, Any] = {
            "transport": "stdio",
            "command": definition.command,
            "args": list(definition.args),
        }
        if definition.cwd:
            config["cwd"] = definition.cwd
        if definition.env:
            env = {key: str(value) for key, value in os.environ.items()}
            env.update({key: str(value) for key, value in context.env.as_dict().items() if value is not None})
            env.update(
                {
                    key: self._resolve_config_value(value, context, f"mcp_servers.{definition.id}.env.{key}")
                    for key, value in definition.env.items()
                }
            )
            config["env"] = env
        return config

    def _http_config(self, definition: McpServerDefinition, context: CustomToolContext) -> dict[str, Any]:
        config: dict[str, Any] = {
            "transport": definition.transport,
            "url": definition.url,
        }
        headers = self._resolved_headers(definition, context)
        auth = self._resolved_auth(definition, context, headers)
        if headers:
            config["headers"] = headers
        if auth is not None:
            config["auth"] = auth
        timeout = definition.timeout or self.DEFAULT_TIMEOUT_SECONDS
        config["timeout"] = timedelta(seconds=timeout) if definition.transport == "streamable_http" else timeout
        return config

    def _resolved_headers(self, definition: McpServerDefinition, context: CustomToolContext) -> dict[str, str]:
        return {
            key: self._resolve_config_value(value, context, f"mcp_servers.{definition.id}.headers.{key}")
            for key, value in definition.headers.items()
        }

    def _resolved_auth(
        self,
        definition: McpServerDefinition,
        context: CustomToolContext,
        headers: dict[str, str],
    ) -> object | None:
        auth = definition.auth
        if auth is None:
            return None
        if auth.type == "bearer":
            token = self._require_env(context, auth.env or "", f"mcp_servers.{definition.id}.auth.env")
            headers["Authorization"] = f"Bearer {token}"
            return None
        if auth.type == "api_key":
            api_key = self._require_env(context, auth.env or "", f"mcp_servers.{definition.id}.auth.env")
            headers[auth.header or ""] = api_key
            return None
        if auth.type == "custom":
            factory = self._load_auth_factory(auth.factory or "")
            self._validate_auth_signature(definition, factory, context, auth.args)
            return factory(context, auth.args)
        raise TeamInstanciatorError(f"Unsupported MCP auth type: {auth.type}")

    def _resolve_config_value(self, value: McpConfigValue, context: CustomToolContext, label: str) -> str:
        if value.value is not None:
            return value.value
        if value.env:
            return self._require_env(context, value.env, label)
        raise TeamInstanciatorError(f"Missing MCP config value: {label}")

    def _require_env(self, context: CustomToolContext, name: str, label: str) -> str:
        if not name:
            raise TeamInstanciatorError(f"Missing required environment value name: {label}")
        value = context.env.get(name)
        if value is None or value == "":
            raise TeamInstanciatorError(f"Missing required environment value: {name}")
        return str(value)

    def _load_auth_factory(self, factory_path: str) -> McpAuthFactoryCallable:
        module_name, separator, function_name = factory_path.partition(":")
        if not separator or not module_name or not function_name:
            raise TeamInstanciatorError(f"Unsupported MCP auth factory: {factory_path}")
        try:
            module = importlib.import_module(module_name)
        except ImportError as error:
            raise TeamInstanciatorError(f"Could not import MCP auth module '{module_name}'.") from error
        try:
            factory = getattr(module, function_name)
        except AttributeError as error:
            raise TeamInstanciatorError(f"MCP auth factory not found: {factory_path}") from error
        if not callable(factory):
            raise TeamInstanciatorError(f"MCP auth factory is not callable: {factory_path}")
        return cast(McpAuthFactoryCallable, factory)

    def _validate_auth_signature(
        self,
        definition: McpServerDefinition,
        factory: McpAuthFactoryCallable,
        context: CustomToolContext,
        args: JsonObject,
    ) -> None:
        try:
            inspect.signature(factory).bind(context, args)
        except ValueError:
            return
        except TypeError as error:
            raise TeamInstanciatorError(
                f"MCP auth factory for '{definition.id}' must accept (context, args)."
            ) from error

    def _normalize_tools(self, definition: McpServerDefinition, result: object) -> list[BaseTool]:
        if isinstance(result, BaseTool):
            return [result]
        if not isinstance(result, Sequence) or isinstance(result, (str, bytes, bytearray)):
            raise TeamInstanciatorError(f"MCP server '{definition.id}' must return a tool or sequence of tools.")
        tools = list(result)
        if not all(isinstance(tool, BaseTool) for tool in tools):
            raise TeamInstanciatorError(f"MCP server '{definition.id}' returned a non-tool value.")
        return cast(list[BaseTool], tools)

    def _filter_exposed_tools(self, definition: McpServerDefinition, tools: list[BaseTool]) -> list[BaseTool]:
        if definition.exposes is None:
            return tools
        exposed = set(definition.exposes)
        names = {tool.name for tool in tools}
        missing = sorted(exposed - names)
        if missing:
            raise TeamInstanciatorError(
                f"MCP server '{definition.id}' exposes mismatch (missing: {', '.join(missing)})."
            )
        return [tool for tool in tools if tool.name in exposed]

    def _default_client(self, connections: dict[str, dict[str, Any]]) -> object:
        try:
            from langchain_mcp_adapters.client import MultiServerMCPClient
        except ImportError as error:
            raise TeamInstanciatorError("The langchain-mcp-adapters package is not installed.") from error
        return MultiServerMCPClient(connections)
