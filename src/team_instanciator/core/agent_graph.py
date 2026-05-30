from __future__ import annotations

from collections.abc import AsyncIterator, Iterator, Mapping, Sequence
from typing import Protocol

from src.team_instanciator.runtime.runnable_config_metadata_injector import RunnableConfigMetadataInjector


class RunnableGraph(Protocol):
    def invoke(self, input: object, config: Mapping[str, object] | None = None, **kwargs: object) -> object:
        ...

    async def ainvoke(self, input: object, config: Mapping[str, object] | None = None, **kwargs: object) -> object:
        ...

    def stream(self, input: object, config: Mapping[str, object] | None = None, **kwargs: object) -> Iterator[object]:
        ...

    def astream(self, input: object, config: Mapping[str, object] | None = None, **kwargs: object) -> AsyncIterator[object]:
        ...

    def astream_events(self, input: object, config: Mapping[str, object] | None = None, **kwargs: object) -> AsyncIterator[object]:
        ...

    def batch(
        self,
        inputs: Sequence[object],
        config: Mapping[str, object] | list[Mapping[str, object] | None] | None = None,
        **kwargs: object,
    ) -> object:
        ...

    async def abatch(
        self,
        inputs: Sequence[object],
        config: Mapping[str, object] | list[Mapping[str, object] | None] | None = None,
        **kwargs: object,
    ) -> object:
        ...

    def with_config(self, config: Mapping[str, object] | None = None, **kwargs: object) -> RunnableGraph:
        ...


class AgentGraph:
    def __init__(
        self,
        graph: RunnableGraph,
        metadata: Mapping[str, object],
        metadata_injector: RunnableConfigMetadataInjector | None = None,
    ) -> None:
        self._graph = graph
        self._metadata = dict(metadata)
        self._metadata_injector = metadata_injector or RunnableConfigMetadataInjector()

    def invoke(self, input: object, config: Mapping[str, object] | None = None, **kwargs: object) -> object:
        return self._graph.invoke(input, config=self._config(config), **kwargs)

    async def ainvoke(self, input: object, config: Mapping[str, object] | None = None, **kwargs: object) -> object:
        return await self._graph.ainvoke(input, config=self._config(config), **kwargs)

    def stream(self, input: object, config: Mapping[str, object] | None = None, **kwargs: object) -> Iterator[object]:
        return self._graph.stream(input, config=self._config(config), **kwargs)

    async def astream(self, input: object, config: Mapping[str, object] | None = None, **kwargs: object) -> AsyncIterator[object]:
        async for chunk in self._graph.astream(input, config=self._config(config), **kwargs):
            yield chunk

    async def astream_events(self, input: object, config: Mapping[str, object] | None = None, **kwargs: object) -> AsyncIterator[object]:
        async for event in self._graph.astream_events(input, config=self._config(config), **kwargs):
            yield event

    def batch(
        self,
        inputs: Sequence[object],
        config: Mapping[str, object] | list[Mapping[str, object] | None] | None = None,
        **kwargs: object,
    ) -> object:
        return self._graph.batch(inputs, config=self._configs(config), **kwargs)

    async def abatch(
        self,
        inputs: Sequence[object],
        config: Mapping[str, object] | list[Mapping[str, object] | None] | None = None,
        **kwargs: object,
    ) -> object:
        return await self._graph.abatch(inputs, config=self._configs(config), **kwargs)

    def with_config(self, config: Mapping[str, object] | None = None, **kwargs: object) -> AgentGraph:
        return AgentGraph(
            self._graph.with_config(self._config(config), **kwargs),
            self._metadata,
            self._metadata_injector,
        )

    def _config(self, config: Mapping[str, object] | None) -> dict[str, object]:
        return self._metadata_injector.inject(config, self._metadata)

    def _configs(
        self,
        config: Mapping[str, object] | list[Mapping[str, object] | None] | None,
    ) -> dict[str, object] | list[dict[str, object]]:
        return self._metadata_injector.inject_many(config, self._metadata)

    def __getattr__(self, name: str) -> object:
        return getattr(self._graph, name)
