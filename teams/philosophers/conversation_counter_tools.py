from __future__ import annotations

from langchain.tools import ToolRuntime
from langchain_core.messages import AIMessage
from langchain_core.tools import StructuredTool

from src.type_defs import JsonObject
from src.team_instanciator.tools.custom_tool_context import CustomToolContext


MESSAGE_LIMIT = 20
OUTBOUND_TOOL_NAMES = {"ask_german_philosopher", "ask_japanese_philosopher"}


def create_conversation_counter_tools(
    context: CustomToolContext,
    _args: JsonObject,
) -> list[StructuredTool]:
    def count_english_messages(runtime: ToolRuntime) -> dict[str, object]:
        """Count English-philosopher messages against the team limit."""

        written_messages = sum(
            1
            for message in context.history.current_messages(runtime)
            if _is_written_english_message(message)
        )
        return {
            "count": written_messages,
            "remaining": max(MESSAGE_LIMIT - written_messages, 0),
            "stop": written_messages >= MESSAGE_LIMIT,
            "recommandation": "continue your conversation"
            if written_messages < MESSAGE_LIMIT
            else "stop",
        }

    return [
        StructuredTool.from_function(
            count_english_messages,
            name="count_english_messages",
            description=(
                "Count English-philosopher messages and report progress "
                f"toward the limit of {MESSAGE_LIMIT}."
            ),
        )
    ]


def _is_written_english_message(message: object) -> bool:
    if not isinstance(message, AIMessage):
        return False
    if message.tool_calls:
        return any(
            tool_call.get("name") in OUTBOUND_TOOL_NAMES
            for tool_call in message.tool_calls
        )
    return isinstance(message.content, str) and bool(message.content.strip())
