from __future__ import annotations

import base64
from collections.abc import Sequence
from typing import TypeGuard

from src.type_defs import JsonObject, is_json_object
from src.webapp.api.conversation_protocol import AttachmentInput, WebConversation


class AttachmentRefFactory:
    def __init__(self, conversation: WebConversation) -> None:
        self._conversation = conversation

    def refs(self, attachments: object, *, author_id: str) -> list[AttachmentInput]:
        if not self._is_attachment_sequence(attachments):
            return []
        return [
            self.ref(attachment, author_id=author_id)
            for attachment in attachments
            if is_json_object(attachment)
        ]

    def ref(self, attachment: JsonObject, *, author_id: str) -> AttachmentInput:
        raw_content = attachment.get("content_base64")
        if not raw_content:
            return attachment
        filename = str(attachment.get("filename") or "attachment")
        return self._conversation.create_public_file_ref(
            filename=filename,
            content=base64.b64decode(str(raw_content)),
            added_by=author_id,
            media_type=str(attachment["media_type"]) if attachment.get("media_type") is not None else None,
        )

    def _is_attachment_sequence(self, value: object) -> TypeGuard[Sequence[object]]:
        return isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray))
