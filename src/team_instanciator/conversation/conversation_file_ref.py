from __future__ import annotations

from dataclasses import dataclass
from typing import TypedDict


class ConversationFileRefDict(TypedDict):
    id: str
    filename: str
    uri: str
    media_type: str | None
    size_bytes: int | None
    added_by: str | None


@dataclass(frozen=True)
class ConversationFileRef:
    id: str
    filename: str
    uri: str
    media_type: str | None = None
    size_bytes: int | None = None
    added_by: str | None = None

    def to_dict(self) -> ConversationFileRefDict:
        return {
            "id": self.id,
            "filename": self.filename,
            "uri": self.uri,
            "media_type": self.media_type,
            "size_bytes": self.size_bytes,
            "added_by": self.added_by,
        }
