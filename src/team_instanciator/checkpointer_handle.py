from __future__ import annotations

from dataclasses import dataclass
from sqlite3 import Connection
from typing import Any


@dataclass
class CheckpointerHandle:
    checkpointer: Any
    connection: Connection | None = None

    def close(self) -> None:
        if self.connection is not None:
            self.connection.close()
