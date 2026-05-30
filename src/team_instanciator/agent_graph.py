from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from .runnable_config_metadata_injector import RunnableConfigMetadataInjector


class AgentGraph:
    def __init__(
        self,
        graph: Any,
        metadata: Mapping[str, Any],
        metadata_injector: RunnableConfigMetadataInjector | None = None,
    ) -> None:
        self._graph = graph
        self._metadata = dict(metadata)
        self._metadata_injector = metadata_injector or RunnableConfigMetadataInjector()

    def invoke(self, input: Any, config: Mapping[str, Any] | None = None, **kwargs: Any) -> Any:
        return self._graph.invoke(input, config=self._config(config), **kwargs)

    async def ainvoke(self, input: Any, config: Mapping[str, Any] | None = None, **kwargs: Any) -> Any:
        return await self._graph.ainvoke(input, config=self._config(config), **kwargs)

    def stream(self, input: Any, config: Mapping[str, Any] | None = None, **kwargs: Any) -> Any:
        return self._graph.stream(input, config=self._config(config), **kwargs)

    async def astream(self, input: Any, config: Mapping[str, Any] | None = None, **kwargs: Any) -> Any:
        async for chunk in self._graph.astream(input, config=self._config(config), **kwargs):
            yield chunk

    async def astream_events(self, input: Any, config: Mapping[str, Any] | None = None, **kwargs: Any) -> Any:
        async for event in self._graph.astream_events(input, config=self._config(config), **kwargs):
            yield event

    def batch(
        self,
        inputs: list[Any],
        config: Mapping[str, Any] | list[Mapping[str, Any] | None] | None = None,
        **kwargs: Any,
    ) -> Any:
        return self._graph.batch(inputs, config=self._configs(config), **kwargs)

    async def abatch(
        self,
        inputs: list[Any],
        config: Mapping[str, Any] | list[Mapping[str, Any] | None] | None = None,
        **kwargs: Any,
    ) -> Any:
        return await self._graph.abatch(inputs, config=self._configs(config), **kwargs)

    def with_config(self, config: Mapping[str, Any] | None = None, **kwargs: Any) -> AgentGraph:
        return AgentGraph(
            self._graph.with_config(self._config(config), **kwargs),
            self._metadata,
            self._metadata_injector,
        )

    def _config(self, config: Mapping[str, Any] | None) -> dict[str, Any]:
        return self._metadata_injector.inject(config, self._metadata)

    def _configs(
        self,
        config: Mapping[str, Any] | list[Mapping[str, Any] | None] | None,
    ) -> dict[str, Any] | list[dict[str, Any]]:
        return self._metadata_injector.inject_many(config, self._metadata)

    def __getattr__(self, name: str) -> Any:
        return getattr(self._graph, name)
