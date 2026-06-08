from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

from langchain.agents.middleware.types import (
    AgentMiddleware,
    ExtendedModelResponse,
    ModelRequest,
    ModelResponse,
    ResponseT,
)
from langchain_core.messages import AIMessage
from langchain_core.tools import BaseTool


class DeepAgentToolVisibilityMiddleware(AgentMiddleware[Any, Any, Any]):
    def __init__(self, *, excluded_tools: frozenset[str]) -> None:
        self.excluded_tools = excluded_tools

    def wrap_model_call(
        self,
        request: ModelRequest[Any],
        handler: Callable[[ModelRequest[Any]], ModelResponse[Any]],
    ) -> ModelResponse[Any]:
        if self.excluded_tools:
            request = request.override(tools=self._visible_tools(request.tools))
        return handler(request)

    async def awrap_model_call(
        self,
        request: ModelRequest[Any],
        handler: Callable[[ModelRequest[Any]], Awaitable[ModelResponse[ResponseT]]],
    ) -> ModelResponse[ResponseT] | AIMessage | ExtendedModelResponse[ResponseT]:
        if self.excluded_tools:
            request = request.override(tools=self._visible_tools(request.tools))
        return await handler(request)

    def _visible_tools(self, tools: list[BaseTool | dict[str, Any]]) -> list[BaseTool | dict[str, Any]]:
        return [tool for tool in tools if self._tool_name(tool) not in self.excluded_tools]

    def _tool_name(self, tool: BaseTool | dict[str, Any]) -> str | None:
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
