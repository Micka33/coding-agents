from __future__ import annotations

import mimetypes
from dataclasses import dataclass
from pathlib import Path
from typing import TypedDict

_FILENAME_MEDIA_TYPES = {
    ".markdown": "text/markdown",
    ".md": "text/markdown",
    ".mdc": "text/markdown",
    ".mdown": "text/markdown",
    ".mkd": "text/markdown",
}


def guess_conversation_media_type(filename: str) -> str | None:
    return mimetypes.guess_type(filename)[0] or _FILENAME_MEDIA_TYPES.get(Path(filename).suffix.lower())


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
