"""Message helpers shared by CLI and resident-agent tools."""

from __future__ import annotations

from typing import Any


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
