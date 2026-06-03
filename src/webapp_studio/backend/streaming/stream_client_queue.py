from __future__ import annotations

import asyncio


class StreamClientQueue:
    def __init__(self, *, max_items: int = 64, put_timeout_seconds: float = 0.25) -> None:
        self._queue: asyncio.Queue[str | None] = asyncio.Queue(maxsize=max_items)
        self._put_timeout_seconds = put_timeout_seconds
        self._closed = False

    async def put(self, frame: str) -> bool:
        if self._closed:
            return False
        try:
            self._queue.put_nowait(frame)
            return True
        except asyncio.QueueFull:
            try:
                await asyncio.wait_for(self._queue.put(frame), timeout=self._put_timeout_seconds)
                return True
            except TimeoutError:
                self.close()
                return False

    async def get(self) -> str | None:
        return await self._queue.get()

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        while True:
            try:
                self._queue.put_nowait(None)
                return
            except asyncio.QueueFull:
                self._queue.get_nowait()

    @property
    def closed(self) -> bool:
        return self._closed
