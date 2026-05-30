from __future__ import annotations

import os
from collections import Counter
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from langchain.tools import ToolRuntime
from langchain_core.messages import RemoveMessage, SystemMessage, ToolMessage
from langgraph.graph.message import REMOVE_ALL_MESSAGES
from langgraph.types import Command

from src.team_loader.agent_definition import AgentDefinition
from src.team_loader.team_definition import TeamDefinition

from .runtime_configuration import RuntimeConfiguration


class EnvView(Mapping[str, Any]):
    """Read-only environment view backed by runtime configuration and os.environ."""

    def __init__(self, configuration: RuntimeConfiguration) -> None:
        self._configuration = configuration

    def get(self, key: str, default: Any = None) -> Any:
        return self._configuration.get(key, default)

    def require(self, key: str) -> Any:
        value = self.get(key)
        if value is None or value == "":
            raise KeyError(f"Missing required environment value: {key}")
        return value

    def as_dict(self, names: Iterable[str] | None = None) -> dict[str, Any]:
        if names is not None:
            return {name: self.get(name) for name in names if self.get(name) is not None}
        values = dict(os.environ)
        values.update(self._configuration.as_dict())
        return values

    def __getitem__(self, key: str) -> Any:
        missing = object()
        value = self.get(key, missing)
        if value is missing:
            raise KeyError(key)
        return value

    def __iter__(self):
        yield from self.as_dict()

    def __len__(self) -> int:
        return len(self.as_dict())


class ConversationHistory:
    """High-level conversation-history helpers for custom tools."""

    def __init__(self, checkpointer: Any | None) -> None:
        self._checkpointer = checkpointer

    @property
    def checkpointer(self) -> Any | None:
        return self._checkpointer

    def thread_id(self, runtime: ToolRuntime) -> str:
        configurable = runtime.config.get("configurable", {}) if runtime.config else {}
        thread_id = configurable.get("thread_id")
        if not isinstance(thread_id, str) or not thread_id:
            raise ValueError("Tool runtime config is missing configurable.thread_id.")
        return thread_id

    def current_state(self, runtime: ToolRuntime) -> Any:
        return runtime.state

    def current_messages(self, runtime: ToolRuntime, key: str = "messages") -> list[Any]:
        messages = self._state_value(runtime.state, key)
        if messages is None:
            return []
        if isinstance(messages, list):
            return list(messages)
        if isinstance(messages, tuple):
            return list(messages)
        return [messages]

    def latest_checkpoint(self, runtime: ToolRuntime) -> Any | None:
        if self._checkpointer is None or not hasattr(self._checkpointer, "get_tuple"):
            return None
        return self._checkpointer.get_tuple(runtime.config)

    def checkpoints(self, runtime: ToolRuntime, *, limit: int = 20) -> list[Any]:
        if self._checkpointer is None or not hasattr(self._checkpointer, "list"):
            return []
        bounded_limit = max(1, limit)
        return list(self._checkpointer.list(runtime.config, limit=bounded_limit))

    def count_messages(self, messages: Sequence[Any]) -> dict[str, int]:
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
        messages: Sequence[Any],
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

    def _kept_messages(self, messages: list[Any], keep_last: int, tool_call_id: str | None) -> list[Any]:
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

    def _state_value(self, state: Any, key: str) -> Any:
        if isinstance(state, Mapping):
            return state.get(key)
        return getattr(state, key, None)

    def _message_role(self, message: Any) -> str:
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

    def _tool_call_count(self, message: Any) -> int:
        return len(self._message_tool_call_ids(message))

    def _message_has_tool_call(self, message: Any, tool_call_id: str) -> bool:
        return tool_call_id in self._message_tool_call_ids(message)

    def _message_tool_call_ids(self, message: Any) -> set[str]:
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

    def _tool_result_call_id(self, message: Any) -> str | None:
        tool_call_id = self._message_value(message, "tool_call_id")
        if isinstance(tool_call_id, str) and tool_call_id:
            return tool_call_id
        return None

    def _usage_counts(self, message: Any) -> tuple[int, int, int]:
        usage = self._usage_metadata(message)
        input_tokens = int((usage.get("input_tokens") or usage.get("prompt_tokens") or 0))
        output_tokens = int((usage.get("output_tokens") or usage.get("completion_tokens") or 0))
        total_tokens = int((usage.get("total_tokens") or input_tokens + output_tokens or 0))
        return input_tokens, output_tokens, total_tokens

    def _usage_metadata(self, message: Any) -> Mapping[str, Any]:
        usage = self._message_value(message, "usage_metadata")
        if isinstance(usage, Mapping):
            return usage
        response_metadata = self._message_value(message, "response_metadata")
        if isinstance(response_metadata, Mapping):
            token_usage = response_metadata.get("token_usage") or response_metadata.get("usage")
            if isinstance(token_usage, Mapping):
                return token_usage
        return {}

    def _message_value(self, message: Any, key: str) -> Any:
        if isinstance(message, Mapping):
            return message.get(key)
        return getattr(message, key, None)


@dataclass(frozen=True)
class CustomToolContext:
    root_dir: Path
    env: EnvView
    runtime_config: RuntimeConfiguration
    agent_config: AgentDefinition
    team_config: TeamDefinition
    history: ConversationHistory
    checkpointer: Any | None = None

    @property
    def agent(self) -> AgentDefinition:
        return self.agent_config

    @property
    def team(self) -> TeamDefinition:
        return self.team_config
