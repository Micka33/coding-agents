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

from webui.pricing import combine_cost_summaries, estimate_messages_cost, load_pricing_catalog


ROOT = Path(__file__).resolve().parents[1]
WEBUI_DIR = Path(__file__).resolve().parent
STATIC_DIR = WEBUI_DIR / "static"
DEFAULT_DB_PATH = ROOT / ".coding-agents" / "checkpoints.sqlite"
PARENT_THREAD_TOKEN = "{parent_thread_id}"


class CheckpointHistoryReader:
    """Read and normalize LangGraph checkpoint messages from SQLite."""

    def __init__(self, db_path: Path, pricing_tier: str = "standard") -> None:
        self.db_path = db_path
        self.serde = JsonPlusSerializer()
        self.pricing_catalog = load_pricing_catalog()
        self.pricing_tier = pricing_tier if pricing_tier in self.pricing_catalog.get("tiers", {}) else "standard"

    def build_state(self, requested_thread_id: str | None = None) -> dict[str, Any]:
        if not self.db_path.exists():
            raise FileNotFoundError(f"Checkpoint database not found: {self.db_path}")

        with self._connect() as conn:
            manifests = self._load_runtime_manifests(conn)
            checkpoint_thread_ids = self._checkpoint_thread_ids(conn)
            checkpoint_metadata = self._checkpoint_metadata_by_thread(conn)
            threads = self._discover_manager_threads(conn, manifests, checkpoint_thread_ids, checkpoint_metadata)
            active_thread_id = self._resolve_active_thread(threads, requested_thread_id, manifests)
            manifest = self._select_runtime_manifest(manifests, active_thread_id, checkpoint_thread_ids)
            runtime_lanes = self._runtime_lanes_for(manifest, active_thread_id)
            runtime_lanes = self._merge_checkpoint_metadata_lanes(runtime_lanes, checkpoint_metadata, active_thread_id)
            relation_tool_targets = self._relation_tool_targets(runtime_lanes)
            agents, task_runs = self._agent_columns_from_lanes(conn, runtime_lanes, relation_tool_targets)

            has_timestamps = any(
                message.get("timestamp", {}).get("epochMs")
                for agent in agents
                for message in agent["messages"]
            )

            thread_cost = combine_cost_summaries(
                [agent["stats"]["cost"] for agent in agents]
                + [run["stats"]["cost"] for run in task_runs],
                pricing_version=self.pricing_catalog["pricing_version"],
                currency=self.pricing_catalog["currency"],
                tier=self.pricing_tier,
            )

            return {
                "dbPath": str(self.db_path),
                "generatedAt": _timestamp_info(datetime.now(UTC).isoformat()),
                "activeThreadId": active_thread_id,
                "threads": threads,
                "agents": agents,
                "taskRuns": task_runs,
                "runtimeManifest": self._manifest_summary(manifest),
                "runtimeLanes": runtime_lanes,
                "cost": thread_cost,
                "pricing": self._pricing_metadata(),
                "hasTimestamps": has_timestamps,
                "residentAgentTools": self._resident_agent_tools_payload(runtime_lanes),
            }

    def build_task_run(self, requested_thread_id: str | None, run_id: str) -> dict[str, Any]:
        if not self.db_path.exists():
            raise FileNotFoundError(f"Checkpoint database not found: {self.db_path}")

        with self._connect() as conn:
            manifests = self._load_runtime_manifests(conn)
            checkpoint_thread_ids = self._checkpoint_thread_ids(conn)
            checkpoint_metadata = self._checkpoint_metadata_by_thread(conn)
            threads = self._discover_manager_threads(conn, manifests, checkpoint_thread_ids, checkpoint_metadata)
            active_thread_id = self._resolve_active_thread(threads, requested_thread_id, manifests)
            manifest = self._select_runtime_manifest(manifests, active_thread_id, checkpoint_thread_ids)
            runtime_lanes = self._runtime_lanes_for(manifest, active_thread_id)
            runtime_lanes = self._merge_checkpoint_metadata_lanes(runtime_lanes, checkpoint_metadata, active_thread_id)
            relation_tool_targets = self._relation_tool_targets(runtime_lanes)

            for lane in self._conversation_lanes(runtime_lanes):
                task_runs = self._load_task_runs(
                    conn,
                    lane["threadId"],
                    include_messages=True,
                    relation_tool_targets=relation_tool_targets,
                )
                manager_messages = self._load_thread_messages(
                    conn,
                    lane["threadId"],
                    lane["id"],
                    source_agent_id=lane.get("agentId"),
                    incoming_source_agent_id=lane.get("sourceAgentId") if lane.get("kind") == "tool-relation" else None,
                    relation_tool_targets=relation_tool_targets,
                )
                self._attach_task_runs(
                    manager_messages,
                    task_runs,
                    source_agent_id=lane.get("agentId"),
                    source_lane_id=lane.get("id"),
                    source_thread_id=lane.get("threadId"),
                )
                for run in task_runs:
                    if run["id"] == run_id:
                        return {
                            "dbPath": str(self.db_path),
                            "generatedAt": _timestamp_info(datetime.now(UTC).isoformat()),
                            "activeThreadId": active_thread_id,
                            "pricing": self._pricing_metadata(),
                            "run": run,
                        }
        raise KeyError(f"Task run not found: {run_id}")

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(f"file:{self.db_path}?mode=ro", uri=True, timeout=1)
        conn.row_factory = sqlite3.Row
        return conn

    def _checkpoint_thread_ids(self, conn: sqlite3.Connection) -> set[str]:
        rows = conn.execute("SELECT DISTINCT thread_id FROM checkpoints WHERE checkpoint_ns = ''").fetchall()
        return {str(row["thread_id"]) for row in rows}

    def _discover_manager_threads(
        self,
        conn: sqlite3.Connection,
        manifests: list[dict[str, Any]],
        checkpoint_thread_ids: set[str],
        checkpoint_metadata: dict[str, dict[str, Any]],
    ) -> list[dict[str, Any]]:
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

        relation_thread_ids = self._relation_thread_ids(checkpoint_thread_ids, manifests)
        threads: list[dict[str, Any]] = []
        for row in rows:
            thread_id = str(row["thread_id"])
            if thread_id in relation_thread_ids or self._is_relation_checkpoint_metadata(
                checkpoint_metadata.get(thread_id)
            ):
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
        manifests: list[dict[str, Any]],
    ) -> str:
        if requested_thread_id:
            base_thread_id = self._parent_thread_id_for_relation(requested_thread_id, manifests) or requested_thread_id
            if any(thread["id"] == base_thread_id for thread in threads):
                return base_thread_id
            return base_thread_id
        if threads:
            return threads[0]["id"]
        return "default"

    def _load_runtime_manifests(self, conn: sqlite3.Connection) -> list[dict[str, Any]]:
        if not self._table_exists(conn, "team_runtime_lanes"):
            return []

        manifest_metadata: dict[str, dict[str, Any]] = {}
        if self._table_exists(conn, "team_runtime_manifests"):
            rows = conn.execute(
                """
                SELECT team_id, manifest_version, created_at, manifest_json
                FROM team_runtime_manifests
                """
            ).fetchall()
            for row in rows:
                manifest_metadata[str(row["team_id"])] = {
                    "teamId": str(row["team_id"]),
                    "manifestVersion": row["manifest_version"],
                    "createdAt": row["created_at"],
                    "manifestJson": row["manifest_json"],
                }

        lane_rows = conn.execute(
            """
            SELECT
                team_id,
                lane_id,
                kind,
                agent_id,
                agent_name,
                source_agent_id,
                target_agent_id,
                tool_name,
                thread_id_pattern
            FROM team_runtime_lanes
            ORDER BY team_id ASC, lane_id ASC
            """
        ).fetchall()

        by_team: dict[str, dict[str, Any]] = {}
        for row in lane_rows:
            team_id = str(row["team_id"])
            manifest = by_team.setdefault(
                team_id,
                {
                    "teamId": team_id,
                    "manifestVersion": manifest_metadata.get(team_id, {}).get("manifestVersion"),
                    "createdAt": manifest_metadata.get(team_id, {}).get("createdAt"),
                    "lanes": [],
                },
            )
            manifest["lanes"].append(
                {
                    "id": str(row["lane_id"]),
                    "laneId": str(row["lane_id"]),
                    "kind": str(row["kind"]),
                    "agentId": _optional_str(row["agent_id"]),
                    "agentName": _optional_str(row["agent_name"]),
                    "sourceAgentId": _optional_str(row["source_agent_id"]),
                    "targetAgentId": _optional_str(row["target_agent_id"]),
                    "toolName": _optional_str(row["tool_name"]),
                    "threadIdPattern": _optional_str(row["thread_id_pattern"]),
                }
            )

        for manifest in by_team.values():
            manifest["lanes"] = self._sorted_runtime_lanes(manifest["lanes"])
        return list(by_team.values())

    def _checkpoint_metadata_by_thread(self, conn: sqlite3.Connection) -> dict[str, dict[str, Any]]:
        rows = conn.execute(
            """
            SELECT thread_id, checkpoint_id, metadata
            FROM checkpoints
            WHERE checkpoint_ns = ''
              AND metadata IS NOT NULL
            ORDER BY thread_id ASC, checkpoint_id ASC
            """
        ).fetchall()

        metadata_by_thread: dict[str, dict[str, Any]] = {}
        for row in rows:
            metadata = self._loads_checkpoint_metadata(row["metadata"])
            if self._is_lane_checkpoint_metadata(metadata):
                metadata_by_thread[str(row["thread_id"])] = metadata
        return metadata_by_thread

    def _loads_checkpoint_metadata(self, value: Any) -> dict[str, Any]:
        if value is None:
            return {}
        if isinstance(value, bytes):
            try:
                value = value.decode("utf-8")
            except UnicodeDecodeError:
                return {}
        if not isinstance(value, str):
            return {}
        try:
            parsed = json.loads(value)
        except json.JSONDecodeError:
            return {}
        return parsed if isinstance(parsed, dict) else {}

    def _is_lane_checkpoint_metadata(self, metadata: dict[str, Any]) -> bool:
        return bool(metadata.get("team_id") and metadata.get("agent_id") and metadata.get("thread_kind"))

    def _is_relation_checkpoint_metadata(self, metadata: dict[str, Any] | None) -> bool:
        return bool(metadata and metadata.get("thread_kind") == "tool-relation")

    def _merge_checkpoint_metadata_lanes(
        self,
        runtime_lanes: list[dict[str, Any]],
        checkpoint_metadata: dict[str, dict[str, Any]],
        active_thread_id: str,
    ) -> list[dict[str, Any]]:
        metadata_lanes = [
            lane
            for thread_id, metadata in checkpoint_metadata.items()
            if (lane := self._lane_from_checkpoint_metadata(thread_id, metadata, active_thread_id))
        ]
        if not metadata_lanes:
            return runtime_lanes

        merged = [
            lane
            for lane in runtime_lanes
            if not (lane.get("id") == "entrypoint" and lane.get("agentId") == "entrypoint")
        ]
        lanes_by_id = {str(lane.get("id") or lane.get("laneId")): lane for lane in merged}
        lanes_by_thread = {str(lane.get("threadId")): lane for lane in merged if lane.get("threadId")}

        for metadata_lane in metadata_lanes:
            existing = lanes_by_id.get(str(metadata_lane["id"])) or lanes_by_thread.get(str(metadata_lane["threadId"]))
            if existing is None:
                merged.append(metadata_lane)
                lanes_by_id[str(metadata_lane["id"])] = metadata_lane
                lanes_by_thread[str(metadata_lane["threadId"])] = metadata_lane
                continue
            for key, value in metadata_lane.items():
                if value is not None:
                    existing[key] = value

        return self._sorted_runtime_lanes(merged)

    def _lane_from_checkpoint_metadata(
        self,
        thread_id: str,
        metadata: dict[str, Any],
        active_thread_id: str,
    ) -> dict[str, Any] | None:
        kind = str(metadata.get("thread_kind") or "")
        if kind not in {"entrypoint", "agent", "tool-relation"}:
            return None
        if kind in {"entrypoint", "agent"} and thread_id != active_thread_id:
            return None
        if kind == "tool-relation" and not thread_id.startswith(f"{active_thread_id}:"):
            return None

        lane_id = str(metadata.get("lane_id") or f"{kind}:{metadata.get('agent_id') or thread_id}")
        agent_id = str(metadata.get("target_agent_id") or metadata.get("agent_id") or lane_id)
        return {
            "id": lane_id,
            "laneId": lane_id,
            "kind": kind,
            "agentId": agent_id,
            "agentName": _optional_str(metadata.get("agent_name")) or agent_id,
            "sourceAgentId": _optional_str(metadata.get("source_agent_id")),
            "targetAgentId": _optional_str(metadata.get("target_agent_id")) or agent_id,
            "toolName": _optional_str(metadata.get("tool_name")),
            "threadIdPattern": None,
            "threadId": thread_id,
        }

    def _sorted_runtime_lanes(self, lanes: list[dict[str, Any]]) -> list[dict[str, Any]]:
        entrypoint_agent_id = next(
            (lane.get("agentId") for lane in lanes if lane.get("kind") == "entrypoint"),
            None,
        )

        def sort_key(lane: dict[str, Any]) -> tuple[int, str]:
            if lane.get("kind") == "entrypoint":
                rank = 0
            elif lane.get("kind") == "tool-relation" and lane.get("sourceAgentId") == entrypoint_agent_id:
                rank = 1
            elif lane.get("kind") == "tool-relation":
                rank = 2
            elif lane.get("kind") == "task-subagent-type":
                rank = 3
            else:
                rank = 4
            return (rank, str(lane.get("laneId") or lane.get("id") or ""))

        return sorted(lanes, key=sort_key)

    def _table_exists(self, conn: sqlite3.Connection, name: str) -> bool:
        row = conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ? LIMIT 1",
            (name,),
        ).fetchone()
        return row is not None

    def _select_runtime_manifest(
        self,
        manifests: list[dict[str, Any]],
        active_thread_id: str,
        checkpoint_thread_ids: set[str],
    ) -> dict[str, Any] | None:
        if not manifests:
            return None
        if len(manifests) == 1:
            return manifests[0]

        def score(manifest: dict[str, Any]) -> tuple[int, int, str]:
            relation_matches = sum(
                1
                for lane in manifest.get("lanes", [])
                if lane.get("kind") == "tool-relation"
                and self._lane_thread_id(lane, active_thread_id) in checkpoint_thread_ids
            )
            exact_team_match = 1 if manifest.get("teamId") == active_thread_id else 0
            return (relation_matches, exact_team_match, str(manifest.get("createdAt") or ""))

        return max(manifests, key=score)

    def _runtime_lanes_for(self, manifest: dict[str, Any] | None, parent_thread_id: str) -> list[dict[str, Any]]:
        if manifest is None:
            return [
                {
                    "id": "entrypoint",
                    "laneId": "entrypoint",
                    "kind": "entrypoint",
                    "agentId": "entrypoint",
                    "agentName": "Entrypoint",
                    "sourceAgentId": None,
                    "targetAgentId": None,
                    "toolName": None,
                    "threadIdPattern": PARENT_THREAD_TOKEN,
                    "threadId": parent_thread_id,
                }
            ]

        lanes = []
        for lane in manifest.get("lanes", []):
            next_lane = dict(lane)
            thread_id = self._lane_thread_id(next_lane, parent_thread_id)
            if thread_id is not None:
                next_lane["threadId"] = thread_id
            lanes.append(next_lane)
        return lanes

    def _manifest_summary(self, manifest: dict[str, Any] | None) -> dict[str, Any] | None:
        if manifest is None:
            return None
        return {
            "teamId": manifest.get("teamId"),
            "manifestVersion": manifest.get("manifestVersion"),
            "createdAt": manifest.get("createdAt"),
        }

    def _conversation_lanes(self, runtime_lanes: list[dict[str, Any]]) -> list[dict[str, Any]]:
        return [lane for lane in runtime_lanes if lane.get("threadId")]

    def _lane_thread_id(self, lane: dict[str, Any], parent_thread_id: str) -> str | None:
        if lane.get("kind") == "task-subagent-type":
            return None
        pattern = lane.get("threadIdPattern")
        if not pattern:
            return parent_thread_id if lane.get("kind") == "entrypoint" else None
        return str(pattern).replace(PARENT_THREAD_TOKEN, parent_thread_id)

    def _relation_thread_ids(self, thread_ids: set[str], manifests: list[dict[str, Any]]) -> set[str]:
        relation_thread_ids = set()
        for thread_id in thread_ids:
            parent_thread_id = self._parent_thread_id_for_relation(thread_id, manifests)
            if parent_thread_id in thread_ids:
                relation_thread_ids.add(thread_id)
        return relation_thread_ids

    def _parent_thread_id_for_relation(self, thread_id: str, manifests: list[dict[str, Any]]) -> str | None:
        for manifest in manifests:
            for lane in manifest.get("lanes", []):
                if lane.get("kind") != "tool-relation":
                    continue
                parent_thread_id = self._parent_from_thread_pattern(thread_id, lane.get("threadIdPattern"))
                if parent_thread_id:
                    return parent_thread_id
        return None

    def _parent_from_thread_pattern(self, thread_id: str, pattern: str | None) -> str | None:
        if not pattern or PARENT_THREAD_TOKEN not in pattern:
            return None
        prefix, suffix = pattern.split(PARENT_THREAD_TOKEN, 1)
        if prefix or not suffix or not thread_id.endswith(suffix):
            return None
        parent_thread_id = thread_id[: -len(suffix)]
        return parent_thread_id or None

    def _relation_tool_targets(self, runtime_lanes: list[dict[str, Any]]) -> dict[tuple[str, str], str]:
        targets: dict[tuple[str, str], str] = {}
        for lane in runtime_lanes:
            if lane.get("kind") != "tool-relation":
                continue
            source_agent_id = lane.get("sourceAgentId")
            tool_name = lane.get("toolName")
            target_agent_id = lane.get("targetAgentId") or lane.get("agentId")
            if source_agent_id and tool_name and target_agent_id:
                targets[(str(source_agent_id), str(tool_name))] = str(target_agent_id)
        return targets

    def _resident_agent_tools_payload(self, runtime_lanes: list[dict[str, Any]]) -> dict[str, Any]:
        return {
            lane["id"]: {
                "sourceAgentId": lane.get("sourceAgentId"),
                "targetAgentId": lane.get("targetAgentId") or lane.get("agentId"),
                "toolName": lane.get("toolName"),
            }
            for lane in runtime_lanes
            if lane.get("kind") == "tool-relation"
        }

    def _agent_columns_from_lanes(
        self,
        conn: sqlite3.Connection,
        runtime_lanes: list[dict[str, Any]],
        relation_tool_targets: dict[tuple[str, str], str],
    ) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        columns: dict[str, dict[str, Any]] = {}
        task_runs: list[dict[str, Any]] = []

        for lane in self._conversation_lanes(runtime_lanes):
            thread_id = lane["threadId"]
            exists = self._thread_exists(conn, thread_id)
            lane_task_runs = self._load_task_runs(
                conn,
                thread_id,
                include_messages=False,
                relation_tool_targets=relation_tool_targets,
            )
            messages = self._load_thread_messages(
                conn,
                thread_id,
                lane["id"],
                source_agent_id=lane.get("agentId"),
                incoming_source_agent_id=lane.get("sourceAgentId") if lane.get("kind") == "tool-relation" else None,
                relation_tool_targets=relation_tool_targets,
            )
            if lane.get("kind") != "entrypoint" and not exists and not messages and not lane_task_runs:
                continue

            self._attach_task_runs(
                messages,
                lane_task_runs,
                source_agent_id=lane.get("agentId"),
                source_lane_id=lane.get("id"),
                source_thread_id=thread_id,
            )
            task_runs.extend(lane_task_runs)

            agent_id = str(lane.get("agentId") or lane["id"])
            column = columns.setdefault(agent_id, self._agent_column_shell(agent_id, lane))
            section_count = len(column["_sections"])
            include_marker = lane.get("kind") != "entrypoint" or section_count > 0
            column["_sections"].append(lane)
            column["_statMessages"].extend(messages)
            column["messages"].extend(self._messages_for_agent_column(lane, messages, include_marker))
            column["exists"] = bool(column["exists"] or exists or messages or lane_task_runs)
            if lane.get("kind") == "entrypoint":
                column["accent"] = "manager"

        agents = []
        for column in columns.values():
            section_count = len(column["_sections"])
            column["threadId"] = self._column_thread_label(column["_sections"])
            column["stats"] = self._agent_stats(column["_statMessages"])
            del column["_sections"]
            del column["_statMessages"]
            if section_count > 1:
                column["kind"] = "agent-group"
            agents.append(column)
        return agents, task_runs

    def _agent_column_shell(self, agent_id: str, lane: dict[str, Any]) -> dict[str, Any]:
        return {
            "id": agent_id,
            "laneId": None,
            "agentId": agent_id,
            "name": str(lane.get("agentName") or lane.get("agentId") or agent_id),
            "shortName": str(lane.get("agentName") or lane.get("agentId") or agent_id),
            "kind": "agent",
            "accent": self._lane_accent(lane),
            "threadId": "",
            "exists": False,
            "messages": [],
            "stats": self._agent_stats([]),
            "_sections": [],
            "_statMessages": [],
        }

    def _messages_for_agent_column(
        self,
        lane: dict[str, Any],
        messages: list[dict[str, Any]],
        include_marker: bool,
    ) -> list[dict[str, Any]]:
        prefixed_messages = [
            {
                **message,
                "id": f"{lane['id']}:{message.get('id') or message.get('index')}",
                "sourceLaneId": lane["id"],
                "sourceThreadId": lane.get("threadId"),
            }
            for message in messages
        ]
        if not include_marker:
            return prefixed_messages
        return [self._lane_section_marker(lane), *prefixed_messages]

    def _lane_section_marker(self, lane: dict[str, Any]) -> dict[str, Any]:
        source_label = self._lane_section_label(lane)
        label = "Conversation déléguée"
        detail = lane.get("threadId") or lane.get("threadIdPattern") or lane["id"]
        text = f"{label}\n{source_label}\n{detail}"
        return {
            "id": f"{lane['id']}:section-marker",
            "index": -1,
            "agentId": lane.get("agentId") or lane["id"],
            "type": "session",
            "name": "Conversation",
            "toolCallId": None,
            "contentText": text,
            "blocks": [{"type": "text", "phase": "conversation", "text": text}],
            "toolCalls": [],
            "timestamp": {"iso": None, "epochMs": None},
            "usage": None,
            "responseMetadata": None,
            "rawType": "ConversationMarker",
        }

    def _lane_section_label(self, lane: dict[str, Any]) -> str:
        if lane.get("kind") == "entrypoint":
            return "Conversation racine"
        source = lane.get("sourceAgentId")
        tool_name = lane.get("toolName")
        if source and tool_name:
            return f"Depuis {source} via {tool_name}"
        if source:
            return f"Depuis {source}"
        return str(lane.get("laneId") or lane["id"])

    def _column_thread_label(self, sections: list[dict[str, Any]]) -> str:
        if len(sections) == 1:
            return str(sections[0].get("threadId") or sections[0].get("threadIdPattern") or "")
        return f"{len(sections)} conversations"

    def _lane_accent(self, lane: dict[str, Any]) -> str:
        if lane.get("kind") == "entrypoint":
            return "manager"
        if lane.get("kind") == "tool-relation":
            return "resident"
        if lane.get("kind") == "task-subagent-type":
            return "disposable"
        return "resident"

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
        *,
        source_agent_id: str | None = None,
        incoming_source_agent_id: str | None = None,
        relation_tool_targets: dict[tuple[str, str], str] | None = None,
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
                source_agent_id=source_agent_id,
                incoming_source_agent_id=incoming_source_agent_id,
                relation_tool_targets=relation_tool_targets,
            )
            for index, message in enumerate(messages)
        ]

    def _load_task_runs(
        self,
        conn: sqlite3.Connection,
        thread_id: str,
        *,
        include_messages: bool,
        relation_tool_targets: dict[tuple[str, str], str] | None = None,
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
            messages = self._load_thread_messages(
                conn,
                thread_id,
                "task-run",
                relation_tool_targets=relation_tool_targets,
                checkpoint_ns=checkpoint_ns,
            )
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
        *,
        source_agent_id: str | None = None,
        source_lane_id: str | None = None,
        source_thread_id: str | None = None,
    ) -> None:
        task_calls = [
            call
            for message in manager_messages
            for call in message["toolCalls"]
            if call["kind"] == "disposable-agent"
        ]

        for call, run in zip(task_calls, task_runs, strict=False):
            target_agent = run.get("targetAgent") or call.get("targetAgent")
            call["sourceAgent"] = source_agent_id
            call["runId"] = run["id"]
            call["runCheckpointNs"] = run["checkpointNs"]
            call["runStats"] = run["stats"]
            run["callId"] = call["id"]
            run["sourceAgent"] = source_agent_id
            run["sourceLaneId"] = source_lane_id
            run["sourceThreadId"] = source_thread_id
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

    def _pricing_metadata(self) -> dict[str, Any]:
        return {
            "tier": self.pricing_tier,
            "availableTiers": list(self.pricing_catalog.get("tiers", {}).keys()),
            "version": self.pricing_catalog.get("pricing_version"),
            "currency": self.pricing_catalog.get("currency", "USD"),
            "tokenUnit": self.pricing_catalog.get("token_unit", "1M tokens"),
        }

    def _agent_stats(self, messages: list[dict[str, Any]]) -> dict[str, Any]:
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
                if call["kind"] == "resident-agent":
                    resident_calls += 1
                if call["kind"] == "disposable-agent":
                    disposable_agent_calls += 1

        return {
            "messages": len(messages),
            "toolCalls": tool_calls,
            "residentAgentCalls": resident_calls,
            "disposableAgentCalls": disposable_agent_calls,
            "thinkingBlocks": thinking_blocks,
            "cost": estimate_messages_cost(
                messages,
                tier=self.pricing_tier,
                catalog=self.pricing_catalog,
            ),
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
    source_agent_id: str | None = None,
    incoming_source_agent_id: str | None = None,
    relation_tool_targets: dict[tuple[str, str], str] | None = None,
) -> dict[str, Any]:
    message_id = _message_id(message) or f"{agent_id}:{index}"
    message_type = _message_type(message)
    content = _message_content(message)
    blocks = _normalize_content_blocks(content)
    tool_calls = _extract_tool_calls(
        message,
        content,
        source_agent_id=source_agent_id,
        relation_tool_targets=relation_tool_targets,
    )
    content_text = _content_to_text(content)

    return {
        "id": message_id,
        "index": index,
        "agentId": agent_id,
        "type": message_type,
        "name": _message_name(message),
        "senderAgentId": incoming_source_agent_id if message_type == "human" else None,
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


def _extract_tool_calls(
    message: Any,
    content: Any,
    *,
    source_agent_id: str | None = None,
    relation_tool_targets: dict[tuple[str, str], str] | None = None,
) -> list[dict[str, Any]]:
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
            "kind": _tool_call_kind(
                str(raw_call.get("name") or ""),
                source_agent_id=source_agent_id,
                relation_tool_targets=relation_tool_targets,
            ),
            "targetAgent": _target_agent(
                raw_call,
                source_agent_id=source_agent_id,
                relation_tool_targets=relation_tool_targets,
            ),
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
                    "kind": _tool_call_kind(
                        name,
                        source_agent_id=source_agent_id,
                        relation_tool_targets=relation_tool_targets,
                    ),
                    "targetAgent": _target_agent(
                        {"name": name, "args": parsed_args},
                        source_agent_id=source_agent_id,
                        relation_tool_targets=relation_tool_targets,
                    ),
                },
            )
            calls[call_id]["rawFunctionId"] = block.get("id")
            calls[call_id]["rawArguments"] = block.get("arguments")
            calls[call_id]["status"] = block.get("status") or calls[call_id].get("status")
            if not calls[call_id].get("args") and isinstance(parsed_args, dict):
                calls[call_id]["args"] = _jsonable(parsed_args)
            calls[call_id]["targetAgent"] = _target_agent(
                calls[call_id],
                source_agent_id=source_agent_id,
                relation_tool_targets=relation_tool_targets,
            )
            calls[call_id]["kind"] = _tool_call_kind(
                name,
                source_agent_id=source_agent_id,
                relation_tool_targets=relation_tool_targets,
            )

    return list(calls.values())


def _tool_call_kind(
    name: str,
    *,
    source_agent_id: str | None = None,
    relation_tool_targets: dict[tuple[str, str], str] | None = None,
) -> str:
    if _relation_tool_target(name, source_agent_id, relation_tool_targets):
        return "resident-agent"
    if name == "task":
        return "disposable-agent"
    return "tool"


def _target_agent(
    raw_call: dict[str, Any],
    *,
    source_agent_id: str | None = None,
    relation_tool_targets: dict[tuple[str, str], str] | None = None,
) -> str | None:
    name = str(raw_call.get("name") or "")
    relation_target = _relation_tool_target(name, source_agent_id, relation_tool_targets)
    if relation_target:
        return relation_target

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


def _relation_tool_target(
    name: str,
    source_agent_id: str | None,
    relation_tool_targets: dict[tuple[str, str], str] | None,
) -> str | None:
    if not relation_tool_targets:
        return None
    if source_agent_id and (source_agent_id, name) in relation_tool_targets:
        return relation_tool_targets[(source_agent_id, name)]

    matches = {target for (source, tool_name), target in relation_tool_targets.items() if tool_name == name}
    if len(matches) == 1:
        return next(iter(matches))
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


def _optional_str(value: Any) -> str | None:
    return str(value) if value is not None else None


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
        pricing_tier = (params.get("pricing_tier") or ["standard"])[0]
        reader = CheckpointHistoryReader(self.server.db_path, pricing_tier=pricing_tier)  # type: ignore[attr-defined]
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
        pricing_tier = (params.get("pricing_tier") or ["standard"])[0]
        if not run_id:
            self._send_json({"error": "run_id is required"}, status=HTTPStatus.BAD_REQUEST)
            return

        reader = CheckpointHistoryReader(self.server.db_path, pricing_tier=pricing_tier)  # type: ignore[attr-defined]
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
