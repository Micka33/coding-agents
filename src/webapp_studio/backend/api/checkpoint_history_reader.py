from __future__ import annotations

import json
import sqlite3
from typing import Any
from urllib.parse import unquote

from langgraph.checkpoint.serde.jsonplus import JsonPlusSerializer

from src.team_instanciator.conversation.payloads import ConversationStateDict
from src.webapp.api.conversation_protocol import WebConversation
from src.webapp_studio.backend.api.time_utils import utc_now_iso
from src.webapp_studio.backend.contracts.checkpoint_summary import CheckpointSummary


class CheckpointHistoryReader:
    def __init__(self) -> None:
        self._serde = JsonPlusSerializer()

    def checkpoints(self, conversation: WebConversation, state: ConversationStateDict) -> list[CheckpointSummary]:
        connection = self._connection(conversation)
        if connection is None:
            return []
        conversation_id = state["conversation_id"]
        branch_id = self._current_branch_id(conversation)
        thread_ids = self._thread_ids(state, conversation_id=conversation_id, branch_id=branch_id)
        if not thread_ids:
            return []
        placeholders = ",".join("?" for _ in thread_ids)
        try:
            rows = connection.execute(
                f"""
                select thread_id, checkpoint_ns, checkpoint_id, parent_checkpoint_id, type, checkpoint, metadata
                from checkpoints
                where thread_id in ({placeholders})
                order by checkpoint_id asc
                """,
                tuple(thread_ids),
            ).fetchall()
        except sqlite3.OperationalError as error:
            if self._is_missing_history_table(error):
                return []
            raise
        return [self._checkpoint_summary(connection, row, seq=index) for index, row in enumerate(rows, start=1)]

    def _thread_ids(self, state: ConversationStateDict, *, conversation_id: str, branch_id: str) -> list[str]:
        thread_ids: list[str] = []
        for participant in state.get("participants", []):
            thread_ids.extend(
                (
                    f"{conversation_id}:branch:{branch_id}:mention:{participant}",
                    f"{conversation_id}:mention:{participant}",
                )
            )
        for branch_thread in state.get("branch_threads", []):
            if not isinstance(branch_thread, dict):
                continue
            thread_branch_id = branch_thread.get("branch_id")
            if thread_branch_id is not None and str(thread_branch_id) != branch_id:
                continue
            physical_thread_id = branch_thread.get("physical_thread_id")
            if isinstance(physical_thread_id, str) and physical_thread_id:
                thread_ids.append(physical_thread_id)
        return list(dict.fromkeys(thread_ids))

    def _connection(self, conversation: WebConversation) -> sqlite3.Connection | None:
        checkpointer_handle = getattr(conversation, "checkpointer_handle", None)
        return getattr(checkpointer_handle, "connection", None)

    def _current_branch_id(self, conversation: WebConversation) -> str:
        runtime = getattr(conversation, "runtime", None)
        current_branch_id = getattr(runtime, "current_branch_id", None)
        if callable(current_branch_id):
            return str(current_branch_id())
        return "branch_main"

    def _checkpoint_summary(self, connection: sqlite3.Connection, row: tuple[Any, ...], *, seq: int) -> CheckpointSummary:
        thread_id, checkpoint_ns, checkpoint_id, parent_checkpoint_id, type_name, checkpoint_blob, metadata_blob = row
        checkpoint = self._checkpoint_payload(type_name, checkpoint_blob)
        metadata = self._metadata(metadata_blob)
        namespace = str(checkpoint_ns or "")
        messages = self._checkpoint_messages(checkpoint) or self._written_messages(
            connection,
            thread_id,
            namespace,
            checkpoint_id,
        )
        agent_id = metadata.get("target_agent_id") or metadata.get("agent_id") or self._agent_id_from_thread(thread_id)
        conversation_event = self._conversation_event(messages)
        return CheckpointSummary(
            id=str(checkpoint_id),
            thread_id=str(thread_id),
            checkpoint_ns=namespace,
            parent_checkpoint_id=str(parent_checkpoint_id) if parent_checkpoint_id is not None else None,
            seq=seq,
            created_at=self._created_at(checkpoint),
            source="langgraph_sqlite",
            metadata=metadata,
            summary={
                "message_count": len(messages),
                "tool_call_count": self._tool_call_count(messages),
                "agent_id": agent_id,
                **conversation_event,
            },
        )

    def _checkpoint_payload(self, type_name: str | None, checkpoint_blob: bytes | None) -> dict[str, Any]:
        if not type_name or not checkpoint_blob:
            return {}
        loaded = self._serde.loads_typed((type_name, checkpoint_blob))
        return loaded if isinstance(loaded, dict) else {}

    def _metadata(self, metadata_blob: bytes | str | None) -> dict[str, Any]:
        raw = metadata_blob.decode("utf-8") if isinstance(metadata_blob, bytes) else metadata_blob or "{}"
        loaded = json.loads(raw)
        return loaded if isinstance(loaded, dict) else {}

    def _created_at(self, checkpoint: dict[str, Any]) -> str:
        timestamp = checkpoint.get("ts") or checkpoint.get("created_at")
        return str(timestamp).replace("+00:00", "Z") if timestamp else utc_now_iso()

    def _checkpoint_messages(self, checkpoint: dict[str, Any]) -> list[Any]:
        channel_values = checkpoint.get("channel_values", {})
        messages = channel_values.get("messages", []) if isinstance(channel_values, dict) else []
        return messages if isinstance(messages, list) else [messages]

    def _written_messages(self, connection: sqlite3.Connection, thread_id: str, checkpoint_ns: str, checkpoint_id: str) -> list[Any]:
        try:
            rows = connection.execute(
                """
                select type, value
                from writes
                where thread_id = ? and checkpoint_ns = ? and checkpoint_id = ? and channel = 'messages'
                order by task_id asc, idx asc
                """,
                (thread_id, checkpoint_ns, checkpoint_id),
            ).fetchall()
        except sqlite3.OperationalError as error:
            if self._is_missing_history_table(error):
                return []
            raise
        return [self._serde.loads_typed((type_name, value)) for type_name, value in rows]

    def _is_missing_history_table(self, error: sqlite3.OperationalError) -> bool:
        message = str(error)
        return "no such table: checkpoints" in message or "no such table: writes" in message

    def _tool_call_count(self, messages: list[Any]) -> int:
        return sum(len(self._tool_calls(message)) for message in messages)

    def _tool_calls(self, message: Any) -> list[Any]:
        if isinstance(message, dict):
            tool_calls = message.get("tool_calls", [])
        else:
            tool_calls = getattr(message, "tool_calls", [])
        return tool_calls if isinstance(tool_calls, list) else []

    def _conversation_event(self, messages: list[Any]) -> dict[str, Any]:
        event_id = None
        event_seq = None
        for message in messages:
            metadata = self._message_metadata(message)
            candidate_seq = metadata.get("conversation_seq")
            if isinstance(candidate_seq, int) and (event_seq is None or candidate_seq >= event_seq):
                event_seq = candidate_seq
                candidate_id = metadata.get("conversation_event_id")
                event_id = str(candidate_id) if candidate_id else None
        result: dict[str, Any] = {}
        if event_id is not None:
            result["event_id"] = event_id
        if event_seq is not None:
            result["event_seq"] = event_seq
        return result

    def _message_metadata(self, message: Any) -> dict[str, Any]:
        if isinstance(message, dict):
            response_metadata = message.get("response_metadata", {})
            additional_kwargs = message.get("additional_kwargs", {})
        else:
            response_metadata = getattr(message, "response_metadata", {})
            additional_kwargs = getattr(message, "additional_kwargs", {})
        metadata: dict[str, Any] = {}
        if isinstance(additional_kwargs, dict):
            metadata.update(additional_kwargs)
        if isinstance(response_metadata, dict):
            metadata.update(response_metadata)
        return metadata

    def _agent_id_from_thread(self, thread_id: str) -> str | None:
        relation_marker = ":agent:"
        if relation_marker in thread_id:
            return unquote(thread_id.rsplit(relation_marker, maxsplit=1)[-1])
        mention_marker = ":mention:"
        return thread_id.rsplit(mention_marker, maxsplit=1)[-1] if mention_marker in thread_id else None
