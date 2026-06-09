from __future__ import annotations

from dataclasses import dataclass
from sqlite3 import Connection
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from src.team_instanciator.runtime.async_checkpointer_loop import AsyncCheckpointerLoop


@dataclass
class CheckpointerHandle:
    checkpointer: object
    connection: Connection | None = None
    async_runner: AsyncCheckpointerLoop | None = None

    def close(self) -> None:
        try:
            if self.async_runner is not None:
                self.async_runner.close()
        finally:
            if self.connection is not None:
                self.connection.close()
