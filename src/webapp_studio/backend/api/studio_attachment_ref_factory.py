from __future__ import annotations

import base64
import binascii
from collections.abc import Sequence
from typing import TypeAlias

from src.team_instanciator.conversation.conversation_file_ref import ConversationFileRef
from src.type_defs import JsonObject, is_json_object
from src.webapp.api.conversation_protocol import WebConversation

AttachmentInput: TypeAlias = ConversationFileRef | JsonObject

MAX_ATTACHMENT_BYTES = 10 * 1024 * 1024
MAX_ATTACHMENT_REQUEST_BYTES = 25 * 1024 * 1024


class StudioAttachmentRefFactory:
    def __init__(self, conversation: WebConversation) -> None:
        self._conversation = conversation

    def refs(self, attachments: Sequence[object], *, author_id: str) -> list[AttachmentInput]:
        refs = []
        total_bytes = 0
        for attachment in attachments:
            if not is_json_object(attachment):
                continue
            ref, size_bytes = self.ref_with_size(attachment, author_id=author_id)
            total_bytes += size_bytes
            if total_bytes > MAX_ATTACHMENT_REQUEST_BYTES:
                raise ValueError("attachment request exceeds the 25 MiB limit.")
            refs.append(ref)
        return refs

    def ref(self, attachment: JsonObject, *, author_id: str) -> AttachmentInput:
        ref, _size_bytes = self.ref_with_size(attachment, author_id=author_id)
        return ref

    def ref_with_size(self, attachment: JsonObject, *, author_id: str) -> tuple[AttachmentInput, int]:
        raw_content = attachment.get("content_base64")
        if not raw_content:
            return attachment, 0
        filename = str(attachment.get("filename") or "attachment")
        try:
            content = base64.b64decode(str(raw_content), validate=True)
        except (binascii.Error, ValueError) as exc:
            raise ValueError("attachment content_base64 is not valid base64.") from exc
        if len(content) > MAX_ATTACHMENT_BYTES:
            raise ValueError("attachment exceeds the 10 MiB file limit.")
        return self._conversation.create_public_file_ref(
            filename=filename,
            content=content,
            added_by=author_id,
            media_type=str(attachment["media_type"]) if attachment.get("media_type") is not None else None,
        ), len(content)
