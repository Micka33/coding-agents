from __future__ import annotations

from collections.abc import Mapping, Sequence

from langchain.tools import ToolRuntime

from src.team_loader.models.relation_definition import RelationDefinition

from src.team_instanciator.conversation.protocols import GraphRegistry
from src.team_instanciator.runtime.runnable_config_metadata_injector import RunnableConfigMetadataInjector
from src.team_instanciator.runtime.thread_id_factory import ThreadIdFactory


class RelationTool:
    def __init__(
        self,
        relation: RelationDefinition,
        registry: GraphRegistry,
        parent_thread_id: str,
        thread_id_factory: ThreadIdFactory,
        checkpoint_metadata: Mapping[str, object],
        metadata_injector: RunnableConfigMetadataInjector | None = None,
    ) -> None:
        self._relation = relation
        self._registry = registry
        self._fallback_parent_thread_id = parent_thread_id
        self._thread_id_factory = thread_id_factory
        self._checkpoint_metadata = dict(checkpoint_metadata)
        self._metadata_injector = metadata_injector or RunnableConfigMetadataInjector()

    def run(self, message: str, runtime: ToolRuntime) -> str:
        """Send a message to a related agent."""

        graph = self._registry.graph(self._relation.target)
        thread_id = self._thread_id_factory.relation(self._parent_thread_id(runtime), self._relation)
        result = graph.invoke(
            {"messages": [{"role": "user", "content": message}]},
            config=self._metadata_injector.inject(
                {"configurable": {"thread_id": thread_id}},
                self._checkpoint_metadata,
            ),
        )
        return self._last_message_text(result)

    def _parent_thread_id(self, runtime: ToolRuntime) -> str:
        configurable = runtime.config.get("configurable", {}) if runtime.config else {}
        thread_id = configurable.get("thread_id")
        if isinstance(thread_id, str) and thread_id:
            return thread_id
        return self._fallback_parent_thread_id

    def _last_message_text(self, result: object) -> str:
        messages = result.get("messages") if isinstance(result, Mapping) else None
        if not isinstance(messages, Sequence) or isinstance(messages, (str, bytes, bytearray)) or not messages:
            return str(result)
        last = messages[-1]
        content = getattr(last, "content", None)
        if content is None and isinstance(last, Mapping):
            content = last.get("content")
        return "" if content is None else str(content)
