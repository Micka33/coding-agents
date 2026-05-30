from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class PublicReply:
    content: str
    source_message_id: str | None = None
