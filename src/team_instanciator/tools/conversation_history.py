from __future__ import annotations

from collections import Counter
from collections.abc import Mapping, Sequence

from langchain.tools import ToolRuntime
from langchain_core.messages import RemoveMessage, SystemMessage, ToolMessage
from langgraph.graph.message import REMOVE_ALL_MESSAGES
from langgraph.types import Command


class ConversationHistory:
    """High-level conversation-history helpers for custom tools."""

    def __init__(self, checkpointer: object | None) -> None:
        self._checkpointer = checkpointer

    @property
    def checkpointer(self) -> object | None:
        return self._checkpointer

    def thread_id(self, runtime: ToolRuntime) -> str:
        configurable = runtime.config.get("configurable", {}) if runtime.config else {}
        thread_id = configurable.get("thread_id")
        if not isinstance(thread_id, str) or not thread_id:
            raise ValueError("Tool runtime config is missing configurable.thread_id.")
        return thread_id

    def current_state(self, runtime: ToolRuntime) -> object:
        return runtime.state

    def current_messages(self, runtime: ToolRuntime, key: str = "messages") -> list[object]:
        messages = self._state_value(runtime.state, key)
        if messages is None:
            return []
        if isinstance(messages, list):
            return list(messages)
        if isinstance(messages, tuple):
            return list(messages)
        return [messages]

    def latest_checkpoint(self, runtime: ToolRuntime) -> object | None:
        get_tuple = getattr(self._checkpointer, "get_tuple", None)
        if not callable(get_tuple):
            return None
        return get_tuple(runtime.config)

    def checkpoints(self, runtime: ToolRuntime, *, limit: int = 20) -> list[object]:
        list_checkpoints = getattr(self._checkpointer, "list", None)
        if not callable(list_checkpoints):
            return []
        bounded_limit = max(1, limit)
        return list(list_checkpoints(runtime.config, limit=bounded_limit))

    def count_messages(self, messages: Sequence[object]) -> dict[str, int]:
        counts: Counter[str] = Counter()
        input_tokens = 0
        output_tokens = 0
        total_tokens = 0
        tool_call_requests = 0

        for message in messages:
            role = self._message_role(message)
            counts[role] += 1
            tool_call_requests += self._tool_call_count(message)
            usage_input, usage_output, usage_total = self._usage_counts(message)
            input_tokens += usage_input
            output_tokens += usage_output
            total_tokens += usage_total

        return {
            "total": len(messages),
            "human": counts["human"],
            "ai": counts["ai"],
            "system": counts["system"],
            "tool": counts["tool"],
            "other": counts["other"],
            "tool_call_requests": tool_call_requests,
            "tool_results": counts["tool"],
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "total_tokens": total_tokens,
        }

    def replace_messages_command(
        self,
        runtime: ToolRuntime,
        messages: Sequence[object],
        *,
        visible_result: str = "Conversation history updated.",
    ) -> Command:
        return Command(
            update={
                "messages": [
                    RemoveMessage(id=REMOVE_ALL_MESSAGES),
                    *messages,
                    self._tool_message(runtime, visible_result),
                ]
            }
        )

    def compact_messages_command(
        self,
        runtime: ToolRuntime,
        *,
        summary: str,
        keep_last: int = 20,
        visible_result: str = "Conversation context compacted.",
    ) -> Command:
        messages = self.current_messages(runtime)
        kept_messages = self._kept_messages(messages, keep_last, runtime.tool_call_id)
        return self.replace_messages_command(
            runtime,
            [SystemMessage(content=summary), *kept_messages],
            visible_result=visible_result,
        )

    def _kept_messages(self, messages: list[object], keep_last: int, tool_call_id: str | None) -> list[object]:
        start = max(len(messages) - keep_last, 0) if keep_last > 0 else len(messages)
        kept_indexes = set(range(start, len(messages)))
        if tool_call_id:
            kept_indexes.update(
                index for index, message in enumerate(messages) if self._message_has_tool_call(message, tool_call_id)
            )

        previous_size = -1
        while previous_size != len(kept_indexes):
            previous_size = len(kept_indexes)
            tool_call_ids = set()
            tool_result_ids = set()
            for index in kept_indexes.copy():
                message = messages[index]
                tool_call_ids.update(self._message_tool_call_ids(message))
                tool_result_id = self._tool_result_call_id(message)
                if tool_result_id:
                    tool_result_ids.add(tool_result_id)

            for index, message in enumerate(messages):
                if self._message_tool_call_ids(message) & tool_result_ids:
                    kept_indexes.add(index)
                tool_result_id = self._tool_result_call_id(message)
                if tool_result_id and tool_result_id in tool_call_ids:
                    kept_indexes.add(index)

        return [message for index, message in enumerate(messages) if index in kept_indexes]

    def _tool_message(self, runtime: ToolRuntime, content: str) -> ToolMessage:
        if not runtime.tool_call_id:
            raise ValueError("Tool runtime is missing tool_call_id.")
        return ToolMessage(content=content, tool_call_id=runtime.tool_call_id)

    def _state_value(self, state: object, key: str) -> object | None:
        if isinstance(state, Mapping):
            return state.get(key)
        return getattr(state, key, None)

    def _message_role(self, message: object) -> str:
        role = self._message_value(message, "role")
        if role is None:
            role = self._message_value(message, "type")
        normalized = str(role or "other").lower()
        if normalized in {"user", "human"}:
            return "human"
        if normalized in {"assistant", "ai"}:
            return "ai"
        if normalized in {"system", "tool"}:
            return normalized
        return "other"

    def _tool_call_count(self, message: object) -> int:
        return len(self._message_tool_call_ids(message))

    def _message_has_tool_call(self, message: object, tool_call_id: str) -> bool:
        return tool_call_id in self._message_tool_call_ids(message)

    def _message_tool_call_ids(self, message: object) -> set[str]:
        tool_calls = self._message_value(message, "tool_calls")
        if not isinstance(tool_calls, list):
            additional_kwargs = self._message_value(message, "additional_kwargs")
            if isinstance(additional_kwargs, Mapping):
                tool_calls = additional_kwargs.get("tool_calls")
        if not isinstance(tool_calls, list):
            return set()
        ids: set[str] = set()
        for call in tool_calls:
            call_id = call.get("id") if isinstance(call, Mapping) else getattr(call, "id", None)
            if isinstance(call_id, str) and call_id:
                ids.add(call_id)
        return ids

    def _tool_result_call_id(self, message: object) -> str | None:
        tool_call_id = self._message_value(message, "tool_call_id")
        if isinstance(tool_call_id, str) and tool_call_id:
            return tool_call_id
        return None

    def _usage_counts(self, message: object) -> tuple[int, int, int]:
        usage = self._usage_metadata(message)
        input_tokens = int((usage.get("input_tokens") or usage.get("prompt_tokens") or 0))
        output_tokens = int((usage.get("output_tokens") or usage.get("completion_tokens") or 0))
        total_tokens = int((usage.get("total_tokens") or input_tokens + output_tokens or 0))
        return input_tokens, output_tokens, total_tokens

    def _usage_metadata(self, message: object) -> Mapping[str, object]:
        usage = self._message_value(message, "usage_metadata")
        if isinstance(usage, Mapping):
            return usage
        response_metadata = self._message_value(message, "response_metadata")
        if isinstance(response_metadata, Mapping):
            token_usage = response_metadata.get("token_usage") or response_metadata.get("usage")
            if isinstance(token_usage, Mapping):
                return token_usage
        return {}

    def _message_value(self, message: object, key: str) -> object | None:
        if isinstance(message, Mapping):
            return message.get(key)
        return getattr(message, key, None)
