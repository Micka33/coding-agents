from __future__ import annotations

from collections.abc import Mapping
from typing import Protocol


class InvokableGraph(Protocol):
    def invoke(
        self,
        input: object,
        config: Mapping[str, object] | None = None,
        **kwargs: object,
    ) -> object:
        ...

    async def ainvoke(
        self,
        input: object,
        config: Mapping[str, object] | None = None,
        **kwargs: object,
    ) -> object:
        ...


class GraphRegistry(Protocol):
    def graph(self, agent_id: str) -> InvokableGraph:
        ...
