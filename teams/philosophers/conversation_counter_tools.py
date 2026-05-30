from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from langchain.tools import ToolRuntime
from langchain_core.tools import BaseTool, StructuredTool

from src.team_instanciator.custom_tool_context import CustomToolContext


def create_conversation_counter_tools(
    context: CustomToolContext,
    args: Mapping[str, object],
) -> Sequence[BaseTool]:
    label = str(args.get("label") or context.agent_config.id)
    limit = _positive_int(args.get("limit"), default=200)
    tool_name = str(args.get("tool_name") or "count_agent_messages")
    outbound_tool_names = frozenset(_string_sequence(args.get("outbound_tool_names")))

    def count_agent_messages(runtime: ToolRuntime) -> dict[str, object]:
        """Count this agent's written conversation messages against its configured limit."""

        messages = context.history.current_messages(runtime)
        direct_messages, outbound_messages = _written_message_counts(messages, outbound_tool_names)
        written_messages = direct_messages + outbound_messages
        return {
            "count": written_messages,
            "remaining": max(limit - written_messages, 0),
            "stop": written_messages >= limit,
            "recommandation": "continue your conversation" if written_messages < limit else "stop",
        }

    return [
        StructuredTool.from_function(
            count_agent_messages,
            name=tool_name,
            description=(
                f"Count {label}'s written conversation messages and report progress "
                f"toward the limit of {limit}."
            ),
        )
    ]


def _written_message_counts(
    messages: Sequence[Any],
    outbound_tool_names: frozenset[str],
) -> tuple[int, int]:
    direct_messages = 0
    outbound_messages = 0

    for message in messages:
        if _message_role(message) != "ai":
            continue

        tool_calls = _message_tool_calls(message)
        if not tool_calls and _message_content(message).strip():
            direct_messages += 1

        for tool_call in tool_calls:
            if _tool_call_name(tool_call) in outbound_tool_names:
                outbound_messages += 1

    return direct_messages, outbound_messages


def _positive_int(value: object, *, default: int) -> int:
    try:
        parsed = int(value) if value is not None else default
    except (TypeError, ValueError):
        return default
    return parsed if parsed > 0 else default


def _string_sequence(value: object) -> tuple[str, ...]:
    if value is None:
        return ()
    if isinstance(value, str):
        return (value,)
    if isinstance(value, Sequence):
        return tuple(str(item) for item in value if str(item))
    return ()


def _message_role(message: Any) -> str:
    role = _message_value(message, "role")
    if role is None:
        role = _message_value(message, "type")
    normalized = str(role or "other").lower()
    if normalized in {"assistant", "ai"}:
        return "ai"
    if normalized in {"user", "human"}:
        return "human"
    if normalized in {"system", "tool"}:
        return normalized
    return "other"


def _message_content(message: Any) -> str:
    content = _message_value(message, "content")
    if isinstance(content, str):
        return content
    if content is None:
        return ""
    return str(content)


def _message_tool_calls(message: Any) -> list[Any]:
    tool_calls = _message_value(message, "tool_calls")
    if not isinstance(tool_calls, list):
        additional_kwargs = _message_value(message, "additional_kwargs")
        if isinstance(additional_kwargs, Mapping):
            tool_calls = additional_kwargs.get("tool_calls")
    return list(tool_calls) if isinstance(tool_calls, list) else []


def _tool_call_name(tool_call: Any) -> str | None:
    name = (
        tool_call.get("name")
        if isinstance(tool_call, Mapping)
        else getattr(tool_call, "name", None)
    )
    if isinstance(name, str) and name:
        return name
    return None


def _message_value(message: Any, key: str) -> Any:
    if isinstance(message, Mapping):
        return message.get(key)
    return getattr(message, key, None)
