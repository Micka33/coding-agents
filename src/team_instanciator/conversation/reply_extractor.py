from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import TypeGuard

from .public_reply import PublicReply


class PublicReplyExtractor:
    def extract(self, result: object) -> PublicReply | None:
        messages = result.get("messages") if isinstance(result, Mapping) else None
        if not self._is_message_sequence(messages):
            return None
        for message in reversed(list(messages)):
            if self._message_type(message) not in {"ai", "assistant"}:
                continue
            text = self._content_text(self._message_value(message, "content")).strip()
            if text:
                return PublicReply(content=text, source_message_id=self._message_id(message))
        return None

    def _message_type(self, message: object) -> str:
        value = self._message_value(message, "type") or self._message_value(message, "role")
        return str(value or "").lower()

    def _message_id(self, message: object) -> str | None:
        value = self._message_value(message, "id")
        return str(value) if value else None

    def _message_value(self, message: object, key: str) -> object | None:
        if isinstance(message, Mapping):
            return message.get(key)
        return getattr(message, key, None)

    def _content_text(self, content: object) -> str:
        if content is None:
            return ""
        if isinstance(content, str):
            return content
        if isinstance(content, list):
            parts: list[str] = []
            for item in content:
                if isinstance(item, Mapping):
                    if item.get("type") == "text":
                        value = item.get("text") or item.get("content")
                        if value:
                            parts.append(str(value))
                elif item:
                    parts.append(str(item))
            return "\n".join(parts)
        return str(content)

    def _is_message_sequence(self, value: object) -> TypeGuard[Sequence[object]]:
        return isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray))
