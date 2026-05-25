"""Local web UI server for LangGraph checkpointed agent histories."""

from __future__ import annotations

import argparse
import json
import mimetypes
import sqlite3
from datetime import UTC, datetime
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, unquote, urlparse

from langchain_core.messages.utils import convert_to_messages
from langgraph.checkpoint.serde.jsonplus import JsonPlusSerializer
from langgraph.graph.message import add_messages
from langgraph.types import Overwrite


ROOT = Path(__file__).resolve().parents[1]
WEBUI_DIR = Path(__file__).resolve().parent
STATIC_DIR = WEBUI_DIR / "static"
DEFAULT_DB_PATH = ROOT / ".coding-agents" / "checkpoints.sqlite"

AGENT_DEFINITIONS = (
    {
        "id": "manager",
        "name": "Engineering manager",
        "shortName": "Manager",
        "threadSuffix": "",
        "kind": "resident",
        "accent": "manager",
    },
    {
        "id": "product-analyst",
        "name": "Product analyst",
        "shortName": "Product",
        "threadSuffix": ":resident:product-analyst",
        "kind": "resident",
        "accent": "product",
    },
    {
        "id": "software-architect",
        "name": "Software architect",
        "shortName": "Architect",
        "threadSuffix": ":resident:software-architect",
        "kind": "resident",
        "accent": "architect",
    },
)

RESIDENT_AGENT_TOOLS = {
    "ask_product_analyst": "product-analyst",
    "ask_software_architect": "software-architect",
}


class CheckpointHistoryReader:
    """Read and normalize LangGraph checkpoint messages from SQLite."""

    def __init__(self, db_path: Path) -> None:
        self.db_path = db_path
        self.serde = JsonPlusSerializer()

    def build_state(self, requested_thread_id: str | None = None) -> dict[str, Any]:
        if not self.db_path.exists():
            raise FileNotFoundError(f"Checkpoint database not found: {self.db_path}")

        with self._connect() as conn:
            threads = self._discover_manager_threads(conn)
            active_thread_id = self._resolve_active_thread(threads, requested_thread_id)
            task_runs = self._load_task_runs(conn, active_thread_id, include_messages=False)
            agents = []
            for definition in AGENT_DEFINITIONS:
                thread_id = f"{active_thread_id}{definition['threadSuffix']}"
                messages = self._load_thread_messages(conn, thread_id, definition["id"])
                if definition["id"] == "manager":
                    self._attach_task_runs(messages, task_runs)
                agents.append(
                    {
                        **definition,
                        "threadId": thread_id,
                        "exists": self._thread_exists(conn, thread_id),
                        "messages": messages,
                        "stats": self._agent_stats(messages),
                    }
                )

            has_timestamps = any(
                message.get("timestamp", {}).get("epochMs")
                for agent in agents
                for message in agent["messages"]
            )

            return {
                "dbPath": str(self.db_path),
                "generatedAt": _timestamp_info(datetime.now(UTC).isoformat()),
                "activeThreadId": active_thread_id,
                "threads": threads,
                "agents": agents,
                "taskRuns": task_runs,
                "hasTimestamps": has_timestamps,
                "residentAgentTools": RESIDENT_AGENT_TOOLS,
            }

    def build_task_run(self, requested_thread_id: str | None, run_id: str) -> dict[str, Any]:
        if not self.db_path.exists():
            raise FileNotFoundError(f"Checkpoint database not found: {self.db_path}")

        with self._connect() as conn:
            threads = self._discover_manager_threads(conn)
            active_thread_id = self._resolve_active_thread(threads, requested_thread_id)
            task_runs = self._load_task_runs(conn, active_thread_id, include_messages=True)
            manager_messages = self._load_thread_messages(conn, active_thread_id, "manager")
            self._attach_task_runs(manager_messages, task_runs)
            for run in task_runs:
                if run["id"] == run_id:
                    return {
                        "dbPath": str(self.db_path),
                        "generatedAt": _timestamp_info(datetime.now(UTC).isoformat()),
                        "activeThreadId": active_thread_id,
                        "run": run,
                    }
        raise KeyError(f"Task run not found: {run_id}")

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(f"file:{self.db_path}?mode=ro", uri=True, timeout=1)
        conn.row_factory = sqlite3.Row
        return conn

    def _discover_manager_threads(self, conn: sqlite3.Connection) -> list[dict[str, Any]]:
        rows = conn.execute(
            """
            SELECT c.thread_id, c.checkpoint_id, c.type, c.checkpoint, counts.count AS checkpoint_count
            FROM checkpoints c
            JOIN (
                SELECT thread_id, MAX(checkpoint_id) AS checkpoint_id, COUNT(*) AS count
                FROM checkpoints
                WHERE checkpoint_ns = ''
                GROUP BY thread_id
            ) counts
                ON counts.thread_id = c.thread_id
               AND counts.checkpoint_id = c.checkpoint_id
            WHERE c.checkpoint_ns = ''
            ORDER BY c.checkpoint_id DESC
            """
        ).fetchall()

        threads: list[dict[str, Any]] = []
        for row in rows:
            thread_id = str(row["thread_id"])
            if ":resident:" in thread_id:
                continue
            checkpoint = self._loads_typed(row["type"], row["checkpoint"], {})
            updated_at = _timestamp_info(checkpoint.get("ts") if isinstance(checkpoint, dict) else None)
            threads.append(
                {
                    "id": thread_id,
                    "checkpointId": row["checkpoint_id"],
                    "checkpointCount": row["checkpoint_count"],
                    "updatedAt": updated_at,
                }
            )
        return threads

    def _resolve_active_thread(
        self,
        threads: list[dict[str, Any]],
        requested_thread_id: str | None,
    ) -> str:
        if requested_thread_id:
            base_thread_id = requested_thread_id.split(":resident:", 1)[0]
            if any(thread["id"] == base_thread_id for thread in threads):
                return base_thread_id
            return base_thread_id
        if threads:
            return threads[0]["id"]
        return "default"

    def _thread_exists(self, conn: sqlite3.Connection, thread_id: str) -> bool:
        row = conn.execute(
            "SELECT 1 FROM checkpoints WHERE thread_id = ? AND checkpoint_ns = '' LIMIT 1",
            (thread_id,),
        ).fetchone()
        return row is not None

    def _load_thread_messages(
        self,
        conn: sqlite3.Connection,
        thread_id: str,
        agent_id: str,
        checkpoint_ns: str = "",
    ) -> list[dict[str, Any]]:
        rows = conn.execute(
            """
            SELECT
                w.checkpoint_id,
                w.task_id,
                w.idx,
                w.type AS write_type,
                w.value AS write_value,
                c.type AS checkpoint_type,
                c.checkpoint AS checkpoint_value
            FROM writes w
            JOIN checkpoints c
                ON c.thread_id = w.thread_id
               AND c.checkpoint_ns = w.checkpoint_ns
               AND c.checkpoint_id = w.checkpoint_id
            WHERE w.thread_id = ?
              AND w.checkpoint_ns = ?
              AND w.channel = 'messages'
            ORDER BY w.checkpoint_id ASC, w.task_id ASC, w.idx ASC
            """,
            (thread_id, checkpoint_ns),
        ).fetchall()

        messages: list[Any] = []
        timestamps_by_id: dict[str, dict[str, Any]] = {}

        for row in rows:
            if not row["write_type"] or row["write_value"] is None:
                continue

            checkpoint = self._loads_typed(
                row["checkpoint_type"],
                row["checkpoint_value"],
                {},
            )
            checkpoint_ts = checkpoint.get("ts") if isinstance(checkpoint, dict) else None
            value = self._loads_typed(row["write_type"], row["write_value"], None)
            if value is None:
                continue

            if isinstance(value, Overwrite):
                messages = _coerce_message_list(value.value)
            else:
                messages = add_messages(messages, value)

            _register_missing_timestamps(messages, timestamps_by_id, checkpoint_ts)

        return [
            _normalize_message(
                message,
                index=index,
                agent_id=agent_id,
                timestamp=timestamps_by_id.get(_message_id(message) or ""),
            )
            for index, message in enumerate(messages)
        ]

    def _load_task_runs(
        self,
        conn: sqlite3.Connection,
        thread_id: str,
        *,
        include_messages: bool,
    ) -> list[dict[str, Any]]:
        rows = conn.execute(
            """
            SELECT
                checkpoint_ns,
                MIN(checkpoint_id) AS first_checkpoint_id,
                MAX(checkpoint_id) AS last_checkpoint_id,
                COUNT(*) AS checkpoint_count
            FROM checkpoints
            WHERE thread_id = ?
              AND checkpoint_ns LIKE 'tools:%'
            GROUP BY checkpoint_ns
            ORDER BY MIN(checkpoint_id) ASC
            """,
            (thread_id,),
        ).fetchall()

        runs: list[dict[str, Any]] = []
        for row in rows:
            checkpoint_ns = str(row["checkpoint_ns"])
            messages = self._load_thread_messages(conn, thread_id, "task-run", checkpoint_ns)
            target_agent = _infer_task_run_agent(messages)
            stats = self._agent_stats(messages)
            run = {
                "id": checkpoint_ns,
                "checkpointNs": checkpoint_ns,
                "threadId": thread_id,
                "name": f"Run {target_agent or 'agent'}",
                "shortName": target_agent or "agent",
                "targetAgent": target_agent,
                "kind": "disposable-run",
                "accent": "disposable",
                "exists": True,
                "firstCheckpointId": row["first_checkpoint_id"],
                "lastCheckpointId": row["last_checkpoint_id"],
                "checkpointCount": row["checkpoint_count"],
                "preview": _task_run_preview(messages),
                "stats": stats,
            }
            if include_messages:
                run["messages"] = messages
            runs.append(run)
        return runs

    def _attach_task_runs(
        self,
        manager_messages: list[dict[str, Any]],
        task_runs: list[dict[str, Any]],
    ) -> None:
        task_calls = [
            call
            for message in manager_messages
            for call in message["toolCalls"]
            if call["kind"] == "disposable-agent"
        ]

        for call, run in zip(task_calls, task_runs, strict=False):
            target_agent = run.get("targetAgent") or call.get("targetAgent")
            call["runId"] = run["id"]
            call["runCheckpointNs"] = run["checkpointNs"]
            call["runStats"] = run["stats"]
            run["callId"] = call["id"]
            run["targetAgent"] = target_agent
            run["name"] = f"Run {target_agent or 'agent'}"
            run["shortName"] = target_agent or run.get("shortName") or "agent"

    def _loads_typed(self, type_name: str | None, blob: bytes | None, fallback: Any) -> Any:
        if not type_name or blob is None:
            return fallback
        try:
            return self.serde.loads_typed((type_name, blob))
        except Exception:
            return fallback

    def _agent_stats(self, messages: list[dict[str, Any]]) -> dict[str, int]:
        tool_calls = 0
        resident_calls = 0
        disposable_agent_calls = 0
        thinking_blocks = 0

        for message in messages:
            for block in message["blocks"]:
                if block["type"] == "reasoning":
                    thinking_blocks += 1
            for call in message["toolCalls"]:
                tool_calls += 1
                if call["name"] in RESIDENT_AGENT_TOOLS:
                    resident_calls += 1
                if call["name"] == "task":
                    disposable_agent_calls += 1

        return {
            "messages": len(messages),
            "toolCalls": tool_calls,
            "residentAgentCalls": resident_calls,
            "disposableAgentCalls": disposable_agent_calls,
            "thinkingBlocks": thinking_blocks,
        }


def _coerce_message_list(value: Any) -> list[Any]:
    if value is None:
        return []
    if not isinstance(value, list):
        value = [value]
    try:
        return list(convert_to_messages(value))
    except Exception:
        return list(value)


def _infer_task_run_agent(messages: list[dict[str, Any]]) -> str | None:
    for message in messages:
        if message.get("type") != "human":
            continue
        for line in str(message.get("contentText") or "").splitlines():
            if line.lower().startswith("role:"):
                value = line.split(":", 1)[1].strip()
                return value or None
    return None


def _task_run_preview(messages: list[dict[str, Any]]) -> str:
    for message in messages:
        if message.get("type") != "human":
            continue
        text = " ".join(str(message.get("contentText") or "").split())
        if len(text) > 260:
            return f"{text[:257]}..."
        return text
    return ""


def _register_missing_timestamps(
    messages: list[Any],
    timestamps_by_id: dict[str, dict[str, Any]],
    checkpoint_ts: Any,
) -> None:
    for message in messages:
        message_id = _message_id(message)
        if not message_id or message_id in timestamps_by_id:
            continue
        timestamp = _extract_message_timestamp(message) or checkpoint_ts
        info = _timestamp_info(timestamp)
        if info["iso"] is not None:
            timestamps_by_id[message_id] = info


def _normalize_message(
    message: Any,
    *,
    index: int,
    agent_id: str,
    timestamp: dict[str, Any] | None,
) -> dict[str, Any]:
    message_id = _message_id(message) or f"{agent_id}:{index}"
    message_type = _message_type(message)
    content = _message_content(message)
    blocks = _normalize_content_blocks(content)
    tool_calls = _extract_tool_calls(message, content)
    content_text = _content_to_text(content)

    return {
        "id": message_id,
        "index": index,
        "agentId": agent_id,
        "type": message_type,
        "name": _message_name(message),
        "toolCallId": _message_tool_call_id(message),
        "contentText": content_text,
        "blocks": blocks,
        "toolCalls": tool_calls,
        "timestamp": timestamp or _timestamp_info(_extract_message_timestamp(message)),
        "usage": _jsonable(getattr(message, "usage_metadata", None)),
        "responseMetadata": _jsonable(getattr(message, "response_metadata", None)),
        "rawType": type(message).__name__,
    }


def _message_id(message: Any) -> str | None:
    if isinstance(message, dict):
        value = message.get("id")
    else:
        value = getattr(message, "id", None)
    return str(value) if value else None


def _message_type(message: Any) -> str:
    if isinstance(message, dict):
        return str(message.get("type") or message.get("role") or "message")
    return str(getattr(message, "type", None) or getattr(message, "role", None) or "message")


def _message_name(message: Any) -> str | None:
    if isinstance(message, dict):
        value = message.get("name")
    else:
        value = getattr(message, "name", None)
    return str(value) if value else None


def _message_tool_call_id(message: Any) -> str | None:
    if isinstance(message, dict):
        value = message.get("tool_call_id") or message.get("toolCallId")
    else:
        value = getattr(message, "tool_call_id", None)
    return str(value) if value else None


def _message_content(message: Any) -> Any:
    if isinstance(message, dict):
        return message.get("content", "")
    return getattr(message, "content", "")


def _extract_message_timestamp(message: Any) -> Any:
    metadata = getattr(message, "response_metadata", None)
    if isinstance(metadata, dict):
        for key in ("created_at", "created", "timestamp"):
            if metadata.get(key):
                return metadata[key]

    additional = getattr(message, "additional_kwargs", None)
    if isinstance(additional, dict):
        for key in ("created_at", "created", "timestamp"):
            if additional.get(key):
                return additional[key]

    for attr in ("created_at", "created", "timestamp"):
        value = getattr(message, attr, None)
        if value:
            return value
    return None


def _normalize_content_blocks(content: Any) -> list[dict[str, Any]]:
    if isinstance(content, str):
        return [{"type": "text", "text": content}] if content else []

    if not isinstance(content, list):
        text = str(content).strip()
        return [{"type": "text", "text": text}] if text else []

    blocks: list[dict[str, Any]] = []
    for block in content:
        if not isinstance(block, dict):
            text = str(block).strip()
            if text:
                blocks.append({"type": "text", "text": text})
            continue

        block_type = str(block.get("type") or "data")
        if block_type == "function_call":
            continue
        if block_type in {"reasoning", "thinking"}:
            blocks.append(
                {
                    "type": "reasoning",
                    "id": block.get("id"),
                    "summary": _summary_text(block.get("summary")),
                    "text": str(block.get("reasoning") or block.get("text") or "").strip(),
                }
            )
            continue
        if block_type == "text":
            text = str(block.get("text") or block.get("content") or "").strip()
            if text:
                blocks.append(
                    {
                        "type": "text",
                        "text": text,
                        "phase": block.get("phase"),
                    }
                )
            continue

        text = block.get("text") or block.get("content")
        if text:
            blocks.append({"type": "text", "text": str(text), "phase": block.get("phase")})
    return blocks


def _summary_text(summary: Any) -> str:
    if not summary:
        return ""
    if isinstance(summary, str):
        return summary.strip()
    if isinstance(summary, list):
        parts: list[str] = []
        for item in summary:
            if isinstance(item, dict):
                value = item.get("text") or item.get("summary") or item.get("content")
                if value:
                    parts.append(str(value))
            elif item:
                parts.append(str(item))
        return "\n".join(parts).strip()
    return str(summary).strip()


def _extract_tool_calls(message: Any, content: Any) -> list[dict[str, Any]]:
    calls: dict[str, dict[str, Any]] = {}

    for raw_call in _jsonable(getattr(message, "tool_calls", None)) or []:
        if not isinstance(raw_call, dict):
            continue
        call_id = str(raw_call.get("id") or raw_call.get("call_id") or "")
        if not call_id:
            continue
        calls[call_id] = {
            "id": call_id,
            "name": str(raw_call.get("name") or "tool"),
            "args": _jsonable(raw_call.get("args") or {}),
            "rawArguments": None,
            "status": raw_call.get("status"),
            "kind": _tool_call_kind(str(raw_call.get("name") or "")),
            "targetAgent": _target_agent(raw_call),
        }

    if isinstance(content, list):
        for block in content:
            if not isinstance(block, dict) or block.get("type") != "function_call":
                continue
            call_id = str(block.get("call_id") or block.get("id") or "")
            if not call_id:
                continue
            parsed_args = _parse_json_maybe(block.get("arguments"))
            name = str(block.get("name") or calls.get(call_id, {}).get("name") or "tool")
            calls.setdefault(
                call_id,
                {
                    "id": call_id,
                    "name": name,
                    "args": _jsonable(parsed_args if isinstance(parsed_args, dict) else {}),
                    "rawArguments": block.get("arguments"),
                    "status": block.get("status"),
                    "kind": _tool_call_kind(name),
                    "targetAgent": _target_agent({"name": name, "args": parsed_args}),
                },
            )
            calls[call_id]["rawFunctionId"] = block.get("id")
            calls[call_id]["rawArguments"] = block.get("arguments")
            calls[call_id]["status"] = block.get("status") or calls[call_id].get("status")
            if not calls[call_id].get("args") and isinstance(parsed_args, dict):
                calls[call_id]["args"] = _jsonable(parsed_args)
            calls[call_id]["targetAgent"] = _target_agent(calls[call_id])
            calls[call_id]["kind"] = _tool_call_kind(name)

    return list(calls.values())


def _tool_call_kind(name: str) -> str:
    if name in RESIDENT_AGENT_TOOLS:
        return "resident-agent"
    if name == "task":
        return "disposable-agent"
    return "tool"


def _target_agent(raw_call: dict[str, Any]) -> str | None:
    name = str(raw_call.get("name") or "")
    if name in RESIDENT_AGENT_TOOLS:
        return RESIDENT_AGENT_TOOLS[name]

    args = raw_call.get("args")
    if isinstance(args, dict):
        subagent_type = args.get("subagent_type")
        if subagent_type:
            return str(subagent_type)
        description = str(args.get("description") or "")
        for line in description.splitlines():
            if line.lower().startswith("role:"):
                return line.split(":", 1)[1].strip()
    return None


def _parse_json_maybe(value: Any) -> Any:
    if not isinstance(value, str):
        return value
    try:
        return json.loads(value)
    except json.JSONDecodeError:
        return value


def _content_to_text(content: Any) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for block in content:
            if isinstance(block, dict):
                block_type = block.get("type")
                if block_type == "function_call":
                    name = block.get("name") or "tool"
                    parts.append(f"[tool call: {name}]")
                elif block_type in {"reasoning", "thinking"}:
                    summary = _summary_text(block.get("summary")) or str(block.get("reasoning") or "").strip()
                    if summary:
                        parts.append(summary)
                else:
                    value = block.get("text") or block.get("content")
                    if value:
                        parts.append(str(value))
            elif block:
                parts.append(str(block))
        return "\n".join(parts).strip()
    return str(content).strip()


def _timestamp_info(value: Any) -> dict[str, Any]:
    if value is None:
        return {"iso": None, "epochMs": None}

    dt: datetime | None = None
    if isinstance(value, datetime):
        dt = value
    elif isinstance(value, (int, float)):
        dt = datetime.fromtimestamp(float(value), tz=UTC)
    elif isinstance(value, str):
        candidate = value.strip()
        if candidate:
            try:
                dt = datetime.fromisoformat(candidate.replace("Z", "+00:00"))
            except ValueError:
                try:
                    dt = datetime.fromtimestamp(float(candidate), tz=UTC)
                except ValueError:
                    dt = None

    if dt is None:
        return {"iso": str(value), "epochMs": None}
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    dt = dt.astimezone(UTC)
    return {
        "iso": dt.isoformat().replace("+00:00", "Z"),
        "epochMs": int(dt.timestamp() * 1000),
    }


def _jsonable(value: Any) -> Any:
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, dict):
        return {str(key): _jsonable(inner) for key, inner in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_jsonable(inner) for inner in value]
    if hasattr(value, "model_dump"):
        try:
            return _jsonable(value.model_dump())
        except Exception:
            pass
    return str(value)


class AgentHistoryRequestHandler(BaseHTTPRequestHandler):
    server_version = "AgentHistoryWebUI/0.1"

    def do_GET(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        if parsed.path == "/api/state":
            self._serve_state(parsed.query)
            return
        if parsed.path == "/api/task-run":
            self._serve_task_run(parsed.query)
            return
        if parsed.path in {"", "/"}:
            self._serve_static_file(STATIC_DIR / "index.html")
            return
        if parsed.path.startswith("/static/"):
            relative = unquote(parsed.path.removeprefix("/static/"))
            self._serve_static_file(STATIC_DIR / relative)
            return
        self.send_error(HTTPStatus.NOT_FOUND)

    def log_message(self, format: str, *args: Any) -> None:
        return

    def _serve_state(self, query: str) -> None:
        params = parse_qs(query)
        thread_id = (params.get("thread_id") or [None])[0]
        reader = CheckpointHistoryReader(self.server.db_path)  # type: ignore[attr-defined]
        try:
            payload = reader.build_state(thread_id)
        except Exception as exc:
            self._send_json({"error": str(exc)}, status=HTTPStatus.INTERNAL_SERVER_ERROR)
            return
        self._send_json(payload)

    def _serve_task_run(self, query: str) -> None:
        params = parse_qs(query)
        thread_id = (params.get("thread_id") or [None])[0]
        run_id = (params.get("run_id") or [None])[0]
        if not run_id:
            self._send_json({"error": "run_id is required"}, status=HTTPStatus.BAD_REQUEST)
            return

        reader = CheckpointHistoryReader(self.server.db_path)  # type: ignore[attr-defined]
        try:
            payload = reader.build_task_run(thread_id, run_id)
        except KeyError as exc:
            self._send_json({"error": str(exc)}, status=HTTPStatus.NOT_FOUND)
            return
        except Exception as exc:
            self._send_json({"error": str(exc)}, status=HTTPStatus.INTERNAL_SERVER_ERROR)
            return
        self._send_json(payload)

    def _serve_static_file(self, path: Path) -> None:
        try:
            resolved = path.resolve()
            resolved.relative_to(STATIC_DIR.resolve())
        except ValueError:
            self.send_error(HTTPStatus.NOT_FOUND)
            return

        if not resolved.is_file():
            self.send_error(HTTPStatus.NOT_FOUND)
            return

        content_type = mimetypes.guess_type(str(resolved))[0] or "application/octet-stream"
        data = resolved.read_bytes()
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        try:
            self.wfile.write(data)
        except (BrokenPipeError, ConnectionResetError):
            return

    def _send_json(self, payload: dict[str, Any], status: HTTPStatus = HTTPStatus.OK) -> None:
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        try:
            self.wfile.write(data)
        except (BrokenPipeError, ConnectionResetError):
            return


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Serve the local agent history web UI.")
    parser.add_argument("--db", type=Path, default=DEFAULT_DB_PATH, help="Path to checkpoints.sqlite.")
    parser.add_argument("--host", default="127.0.0.1", help="Host to bind.")
    parser.add_argument("--port", type=int, default=8765, help="Port to bind.")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    db_path = args.db.expanduser().resolve()
    server = ThreadingHTTPServer((args.host, args.port), AgentHistoryRequestHandler)
    server.db_path = db_path  # type: ignore[attr-defined]
    url = f"http://{args.host}:{args.port}"
    print(f"Agent history web UI: {url}")
    print(f"SQLite checkpoints: {db_path}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print()
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
