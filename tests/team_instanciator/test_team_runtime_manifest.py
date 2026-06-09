from __future__ import annotations

import json
import sqlite3
import unittest

from src.team_instanciator.runtime.checkpointer_handle import CheckpointerHandle
from src.team_instanciator.manifest.team_runtime_manifest_builder import TeamRuntimeManifestBuilder
from src.team_instanciator.manifest.team_runtime_manifest_store import TeamRuntimeManifestStore
from src.team_loader.models.conversation_settings import AgentConversationSettings, TeamConversationSettings
from tests.support import agent, relation, team


class TeamRuntimeManifestTests(unittest.TestCase):
    def test_builder_creates_entrypoint_tool_relation_and_unique_subagent_type_lanes(self) -> None:
        team_config = team(
            team_id="product",
            agents={
                "entry": agent("entry", entrypoint=True),
                "worker": agent("worker"),
                "reviewer": agent("reviewer"),
            },
            relations=(
                relation(source="entry", target="worker", relation_type="tool", tool_name="ask_worker"),
                relation(source="entry", target="reviewer", relation_type="subagent", tool_name=None),
                relation(source="worker", target="reviewer", relation_type="subagent", tool_name=None),
            ),
        )

        manifest = TeamRuntimeManifestBuilder().build(team_config)

        self.assertEqual(manifest.team_id, "product")
        self.assertEqual(
            [lane.lane_id for lane in manifest.lanes],
            [
                "entrypoint:entry",
                "relation:rel_worker",
                "task-subagent-type:reviewer",
            ],
        )

    def test_builder_handles_team_without_entrypoint(self) -> None:
        manifest = TeamRuntimeManifestBuilder().build(team(agents={"worker": agent("worker")}))

        self.assertEqual(manifest.lanes, ())

    def test_builder_adds_mention_lanes_for_conversation_participants(self) -> None:
        team_config = team(
            team_id="product",
            agents={
                "entry": agent("entry", entrypoint=True),
                "architect": agent("architect"),
            },
            agent_references={
                "entry": agent("entry", entrypoint=True),
                "architect": agent("architect"),
            },
            conversation=TeamConversationSettings.from_mapping({}),
        )
        team_config.agent_references["entry"].conversation = AgentConversationSettings()
        team_config.agent_references["architect"].conversation = AgentConversationSettings()

        manifest = TeamRuntimeManifestBuilder().build(team_config)

        mention_lanes = [lane for lane in manifest.lanes if lane.kind == "mention"]
        self.assertEqual([lane.lane_id for lane in mention_lanes], ["mention:entry", "mention:architect"])
        self.assertEqual(mention_lanes[0].thread_id_pattern, "{parent_thread_id}:mention:entry")

    def test_builder_skips_nonparticipants_when_conversation_is_enabled(self) -> None:
        team_config = team(
            agents={
                "entry": agent("entry", entrypoint=True),
                "architect": agent("architect"),
            },
            agent_references={
                "entry": agent("entry", entrypoint=True),
                "architect": agent("architect"),
            },
            conversation=TeamConversationSettings.from_mapping({}),
        )
        team_config.agent_references["entry"].conversation = AgentConversationSettings()
        team_config.agent_references["architect"].conversation = None

        manifest = TeamRuntimeManifestBuilder().build(team_config)

        self.assertEqual([lane.lane_id for lane in manifest.lanes if lane.kind == "mention"], ["mention:entry"])

    def test_store_persists_manifest_and_replaces_lanes_when_connection_exists(self) -> None:
        connection = sqlite3.connect(":memory:")
        handle = CheckpointerHandle("checkpointer", connection)
        manifest = TeamRuntimeManifestBuilder().build(
            team(
                team_id="product",
                agents={"entry": agent("entry", entrypoint=True), "worker": agent("worker")},
                relations=(relation(source="entry", target="worker", relation_type="tool", tool_name="ask_worker"),),
            )
        )
        store = TeamRuntimeManifestStore()

        store.persist(CheckpointerHandle("checkpointer"), manifest)
        connection.execute(
            """
            create table team_runtime_lanes (
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
        store.persist(handle, manifest)
        store.persist(handle, manifest)

        manifest_row = connection.execute("select manifest_json from team_runtime_manifests where team_id = 'product'").fetchone()
        lane_rows = connection.execute("select lane_id, kind from team_runtime_lanes order by lane_id").fetchall()
        relation_row = connection.execute("select relation_id, thread_id_pattern from team_runtime_lanes where lane_id = 'relation:rel_worker'").fetchone()

        self.assertEqual(json.loads(manifest_row[0])["team_id"], "product")
        self.assertEqual(
            lane_rows,
            [
                ("entrypoint:entry", "entrypoint"),
                ("relation:rel_worker", "tool-relation"),
            ],
        )
        self.assertEqual(relation_row, ("rel_worker", "{parent_thread_id}:relation:rel_worker:agent:worker"))
        handle.close()


if __name__ == "__main__":
    unittest.main()
