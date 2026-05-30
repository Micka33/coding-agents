from __future__ import annotations

from dataclasses import dataclass
from sqlite3 import Connection


@dataclass
class CheckpointerHandle:
    checkpointer: object
    connection: Connection | None = None

    def close(self) -> None:
        if self.connection is not None:
            self.connection.close()
