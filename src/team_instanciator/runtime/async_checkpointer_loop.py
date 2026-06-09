from __future__ import annotations

import asyncio
import threading
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import TypeVar

import aiosqlite
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver

T = TypeVar("T")


class AsyncCheckpointerLoop:
    def __init__(self) -> None:
        self._ready = threading.Event()
        self._loop: asyncio.AbstractEventLoop | None = None
        self._sqlite_connection: aiosqlite.Connection | None = None
        self._thread = threading.Thread(target=self._run_loop, name="async-sqlite-checkpointer", daemon=True)
        self._thread.start()
        self._ready.wait()

    def start_sqlite(self, path: Path) -> AsyncSqliteSaver:
        async def create() -> AsyncSqliteSaver:
            connection = await aiosqlite.connect(str(path))
            try:
                await connection.execute("PRAGMA busy_timeout = 5000")
                await connection.commit()
                saver = AsyncSqliteSaver(connection)
                await saver.setup()
            except BaseException:
                await connection.close()
                raise
            self._sqlite_connection = connection
            return saver

        return self.run(create)

    def run(self, coroutine_factory: Callable[[], Awaitable[T]]) -> T:
        loop = self._loop
        if loop is None or not loop.is_running():
            raise RuntimeError("Async checkpointer loop is not running.")
        if threading.get_ident() == self._thread.ident:
            raise RuntimeError("Cannot synchronously wait on the async checkpointer loop from its owning thread.")

        async def execute() -> T:
            return await coroutine_factory()

        return asyncio.run_coroutine_threadsafe(execute(), loop).result()

    def close(self) -> None:
        loop = self._loop
        if loop is None:
            return
        try:
            if self._sqlite_connection is not None and loop.is_running():
                connection = self._sqlite_connection
                self._sqlite_connection = None
                self.run(connection.close)
        finally:
            if loop.is_running():
                loop.call_soon_threadsafe(loop.stop)
            self._thread.join()
            self._loop = None

    def _run_loop(self) -> None:
        loop = asyncio.new_event_loop()
        self._loop = loop
        asyncio.set_event_loop(loop)
        self._ready.set()
        try:
            loop.run_forever()
            loop.run_until_complete(loop.shutdown_asyncgens())
        finally:
            loop.close()
