from __future__ import annotations

from typing import Any

from langchain.tools import ToolRuntime

from coding_agents.team_loader.relation_definition import RelationDefinition

from .thread_id_factory import ThreadIdFactory


class RelationTool:
    def __init__(
        self,
        relation: RelationDefinition,
        registry: Any,
        parent_thread_id: str,
        thread_id_factory: ThreadIdFactory,
    ) -> None:
        self._relation = relation
        self._registry = registry
        self._fallback_parent_thread_id = parent_thread_id
        self._thread_id_factory = thread_id_factory

    def run(self, message: str, runtime: ToolRuntime) -> str:
        """Send a message to a related agent."""

        graph = self._registry.graph(self._relation.target)
        thread_id = self._thread_id_factory.relation(self._parent_thread_id(runtime), self._relation)
        result = graph.invoke(
            {"messages": [{"role": "user", "content": message}]},
            config={"configurable": {"thread_id": thread_id}},
        )
        return self._last_message_text(result)

    def _parent_thread_id(self, runtime: ToolRuntime) -> str:
        configurable = runtime.config.get("configurable", {}) if runtime.config else {}
        thread_id = configurable.get("thread_id")
        if isinstance(thread_id, str) and thread_id:
            return thread_id
        return self._fallback_parent_thread_id

    def _last_message_text(self, result: Any) -> str:
        messages = result.get("messages") if isinstance(result, dict) else None
        if not messages:
            return str(result)
        last = messages[-1]
        content = getattr(last, "content", None)
        if content is None and isinstance(last, dict):
            content = last.get("content")
        return "" if content is None else str(content)
