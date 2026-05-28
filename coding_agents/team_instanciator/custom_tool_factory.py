from __future__ import annotations

import importlib
import inspect
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from langchain_core.tools import BaseTool

from coding_agents.team_loader.custom_tool_definition import CustomToolDefinition

from .custom_tool_context import CustomToolContext
from .scoped_read_tools_factory import ScopedReadToolsFactory
from .team_instanciator_error import TeamInstanciatorError


class CustomToolFactory:
    _LEGACY_SCOUT_FACTORY = "coding_agents.scout:scout_tools"

    def create(self, definition: CustomToolDefinition, context: CustomToolContext) -> list[BaseTool]:
        if definition.factory == self._LEGACY_SCOUT_FACTORY:
            return self._create_legacy_scoped_read_tools(definition, context)

        factory = self._load_factory(definition.factory)
        self._validate_signature(definition, factory, context)
        result = factory(context, definition.args)
        tools = self._normalize_tools(definition, result)
        self._validate(definition, tools)
        return tools

    def _load_factory(self, factory_path: str) -> Any:
        module_name, separator, function_name = factory_path.partition(":")
        if not separator or not module_name or not function_name:
            raise TeamInstanciatorError(f"Unsupported custom tool factory: {factory_path}")
        try:
            module = importlib.import_module(module_name)
        except ImportError as error:
            raise TeamInstanciatorError(f"Could not import custom tool module '{module_name}'.") from error
        try:
            factory = getattr(module, function_name)
        except AttributeError as error:
            raise TeamInstanciatorError(f"Custom tool factory not found: {factory_path}") from error
        if not callable(factory):
            raise TeamInstanciatorError(f"Custom tool factory is not callable: {factory_path}")
        return factory

    def _validate_signature(self, definition: CustomToolDefinition, factory: Any, context: CustomToolContext) -> None:
        try:
            inspect.signature(factory).bind(context, definition.args)
        except ValueError:
            return
        except TypeError as error:
            raise TeamInstanciatorError(
                f"Custom tool factory '{definition.factory}' must accept (context, args)."
            ) from error

    def _normalize_tools(self, definition: CustomToolDefinition, result: Any) -> list[BaseTool]:
        if isinstance(result, BaseTool):
            return [result]
        if not isinstance(result, Sequence):
            raise TeamInstanciatorError(f"Custom tool factory '{definition.id}' must return a tool or sequence of tools.")
        tools = list(result)
        if not all(isinstance(tool, BaseTool) for tool in tools):
            raise TeamInstanciatorError(f"Custom tool factory '{definition.id}' returned a non-tool value.")
        return tools

    def _validate(self, definition: CustomToolDefinition, tools: list[BaseTool]) -> None:
        try:
            definition.validate_returned_tools(tuple(tool.name for tool in tools))
        except ValueError as error:
            raise TeamInstanciatorError(str(error)) from error

    def _create_legacy_scoped_read_tools(
        self,
        definition: CustomToolDefinition,
        context: CustomToolContext,
    ) -> list[BaseTool]:
        if definition.factory == "coding_agents.scout:scout_tools":
            tools = ScopedReadToolsFactory().create(self._root_dir(definition, context))
            self._validate(definition, tools)
            return tools

        raise TeamInstanciatorError(f"Unsupported custom tool factory: {definition.factory}")

    def _root_dir(self, definition: CustomToolDefinition, context: CustomToolContext):
        raw_root = definition.args.get("root_dir", context.root_dir)
        custom_root = Path(str(raw_root))
        if custom_root.is_absolute():
            return custom_root
        return (context.root_dir / custom_root).resolve()
