"""Message helpers shared by CLI and resident-agent tools."""

from __future__ import annotations

from typing import Any


ConversationTurn = tuple[str, str]


def last_message_text(result: dict[str, Any]) -> str:
    """Extract readable text from the last message in an agent result."""

    messages = result.get("messages") or []
    if not messages:
        return "(no response)"

    message = messages[-1]
    text = getattr(message, "text", None)
    if text:
        return str(text)

    content = getattr(message, "content", message)
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for block in content:
            if isinstance(block, dict):
                value = block.get("text") or block.get("content")
                if value:
                    parts.append(str(value))
            else:
                parts.append(str(block))
        return "\n".join(parts).strip() or "(empty response)"
    return str(content)


def conversation_transcript(messages: list[Any]) -> list[ConversationTurn]:
    """Return user-visible conversation turns from persisted graph messages."""

    transcript: list[ConversationTurn] = []
    for message in messages:
        role = _message_role(message)
        if role is None:
            continue

        text = message_text(message)
        if not text:
            continue

        transcript.append((role, text))

    return transcript


def message_text(message: Any) -> str:
    """Extract readable text from one message."""

    if isinstance(message, dict):
        content = message.get("content", message)
        return _content_text(content)

    text = getattr(message, "text", None)
    if text:
        return str(text).strip()

    content = getattr(message, "content", message)
    return _content_text(content)


def _content_text(content: Any) -> str:
    if isinstance(content, str):
        return content.strip()
    if isinstance(content, list):
        parts: list[str] = []
        for block in content:
            if isinstance(block, dict):
                value = block.get("text") or block.get("content")
                if value:
                    parts.append(str(value))
            else:
                parts.append(str(block))
        return "\n".join(parts).strip()
    return str(content).strip()


def _message_role(message: Any) -> str | None:
    if isinstance(message, dict):
        message_type = message.get("type")
        role = message.get("role")
        if message_type == "human" or role == "user":
            return "user"
        if message_type == "ai" or role == "assistant":
            return "manager"
        return None

    message_type = getattr(message, "type", None)
    if message_type == "human":
        return "user"
    if message_type == "ai":
        return "manager"

    role = getattr(message, "role", None)
    if role == "user":
        return "user"
    if role == "assistant":
        return "manager"

    return None
