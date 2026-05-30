from __future__ import annotations

import importlib
import inspect
from collections.abc import Callable, Sequence
from typing import cast

from langchain_core.tools import BaseTool

from src.type_defs import JsonObject
from src.team_loader.models.custom_tool_definition import CustomToolDefinition

from src.team_instanciator.tools.custom_tool_context import CustomToolContext
from src.team_instanciator.errors.team_instanciator_error import TeamInstanciatorError

CustomToolFactoryCallable = Callable[[CustomToolContext, JsonObject], object]


class CustomToolFactory:
    def create(self, definition: CustomToolDefinition, context: CustomToolContext) -> list[BaseTool]:
        factory = self._load_factory(definition.factory)
        self._validate_signature(definition, factory, context)
        result = factory(context, definition.args)
        tools = self._normalize_tools(definition, result)
        self._validate(definition, tools)
        return tools

    def _load_factory(self, factory_path: str) -> CustomToolFactoryCallable:
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
        return cast(CustomToolFactoryCallable, factory)

    def _validate_signature(
        self,
        definition: CustomToolDefinition,
        factory: CustomToolFactoryCallable,
        context: CustomToolContext,
    ) -> None:
        try:
            inspect.signature(factory).bind(context, definition.args)
        except ValueError:
            return
        except TypeError as error:
            raise TeamInstanciatorError(
                f"Custom tool factory '{definition.factory}' must accept (context, args)."
            ) from error

    def _normalize_tools(self, definition: CustomToolDefinition, result: object) -> list[BaseTool]:
        if isinstance(result, BaseTool):
            return [result]
        if not isinstance(result, Sequence) or isinstance(result, (str, bytes, bytearray)):
            raise TeamInstanciatorError(f"Custom tool factory '{definition.id}' must return a tool or sequence of tools.")
        tools = list(result)
        if not all(isinstance(tool, BaseTool) for tool in tools):
            raise TeamInstanciatorError(f"Custom tool factory '{definition.id}' returned a non-tool value.")
        return cast(list[BaseTool], tools)

    def _validate(self, definition: CustomToolDefinition, tools: list[BaseTool]) -> None:
        try:
            definition.validate_returned_tools(tuple(tool.name for tool in tools))
        except ValueError as error:
            raise TeamInstanciatorError(str(error)) from error
