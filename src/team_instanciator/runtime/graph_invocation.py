from __future__ import annotations

import asyncio
import threading
from collections.abc import Awaitable, Mapping
from typing import Any

from src.team_instanciator.runtime.async_checkpointer_loop import AsyncCheckpointerLoop


def invoke_graph_sync(
    graph: Any,
    input: Any,
    *,
    config: Mapping[str, object] | None = None,
    async_runner: AsyncCheckpointerLoop | None = None,
    **kwargs: Any,
) -> Any:
    ainvoke = getattr(graph, "ainvoke", None)
    if async_runner is not None:
        if not callable(ainvoke):
            raise TypeError("Async checkpointer invocations require graph.ainvoke support.")
        return async_runner.run(lambda: ainvoke(input, config=config, **kwargs))
    if callable(ainvoke):
        return _run_coroutine_sync(ainvoke(input, config=config, **kwargs))
    return graph.invoke(input, config=config, **kwargs)


def _run_coroutine_sync(awaitable: Awaitable[Any]) -> Any:
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(awaitable)

    result: dict[str, Any] = {}

    def run() -> None:
        try:
            result["value"] = asyncio.run(awaitable)
        except BaseException as exc:
            result["error"] = exc

    thread = threading.Thread(target=run, name="graph-async-invocation")
    thread.start()
    thread.join()
    if "error" in result:
        raise result["error"]
    return result.get("value")
