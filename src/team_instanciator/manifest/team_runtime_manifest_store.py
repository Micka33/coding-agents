from __future__ import annotations

import json
from datetime import datetime, timezone

from src.team_instanciator.runtime.checkpointer_handle import CheckpointerHandle
from src.team_instanciator.manifest.team_runtime_manifest import TeamRuntimeManifest


class TeamRuntimeManifestStore:
    def persist(self, checkpointer_handle: CheckpointerHandle, manifest: TeamRuntimeManifest) -> None:
        if checkpointer_handle.connection is None:
            return
        connection = checkpointer_handle.connection
        connection.execute(
            """
            create table if not exists team_runtime_manifests (
                team_id text primary key,
                manifest_version integer not null,
                created_at text not null,
                manifest_json text not null
            )
            """
        )
        connection.execute(
            """
            create table if not exists team_runtime_lanes (
                team_id text not null,
                lane_id text not null,
                kind text not null,
                agent_id text,
                agent_name text,
                source_agent_id text,
                target_agent_id text,
                tool_name text,
                thread_id_pattern text,
                primary key (team_id, lane_id)
            )
            """
        )
        self._upsert_manifest(checkpointer_handle, manifest)
        self._replace_lanes(checkpointer_handle, manifest)
        connection.commit()

    def _upsert_manifest(self, checkpointer_handle: CheckpointerHandle, manifest: TeamRuntimeManifest) -> None:
        checkpointer_handle.connection.execute(
            """
            insert into team_runtime_manifests (team_id, manifest_version, created_at, manifest_json)
            values (?, ?, ?, ?)
            on conflict(team_id) do update set
                manifest_version = excluded.manifest_version,
                created_at = excluded.created_at,
                manifest_json = excluded.manifest_json
            """,
            (
                manifest.team_id,
                manifest.manifest_version,
                datetime.now(timezone.utc).isoformat(),
                json.dumps(manifest.to_dict(), ensure_ascii=False),
            ),
        )

    def _replace_lanes(self, checkpointer_handle: CheckpointerHandle, manifest: TeamRuntimeManifest) -> None:
        checkpointer_handle.connection.execute("delete from team_runtime_lanes where team_id = ?", (manifest.team_id,))
        for lane in manifest.lanes:
            checkpointer_handle.connection.execute(
                """
                insert into team_runtime_lanes (
                    team_id,
                    lane_id,
                    kind,
                    agent_id,
                    agent_name,
                    source_agent_id,
                    target_agent_id,
                    tool_name,
                    thread_id_pattern
                )
                values (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    manifest.team_id,
                    lane.lane_id,
                    lane.kind,
                    lane.agent_id,
                    lane.agent_name,
                    lane.source_agent_id,
                    lane.target_agent_id,
                    lane.tool_name,
                    lane.thread_id_pattern,
                ),
            )
