from __future__ import annotations

import json
import sqlite3
import unittest

from src.team_instanciator.checkpointer_handle import CheckpointerHandle
from src.team_instanciator.team_runtime_manifest_builder import TeamRuntimeManifestBuilder
from src.team_instanciator.team_runtime_manifest_store import TeamRuntimeManifestStore
from tests.support import agent, relation, team


class TeamRuntimeManifestTests(unittest.TestCase):
    def test_builder_creates_entrypoint_tool_relation_and_unique_subagent_type_lanes(self) -> None:
        team_config = team(
            team_id="product",
            agents={
                "entry": agent("entry", name="Entry", entrypoint=True),
                "worker": agent("worker", name="Worker"),
                "reviewer": agent("reviewer", name="Reviewer"),
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
                "relation:entry:ask_worker:worker",
                "task-subagent-type:reviewer",
            ],
        )

    def test_builder_handles_team_without_entrypoint(self) -> None:
        manifest = TeamRuntimeManifestBuilder().build(team(agents={"worker": agent("worker")}))

        self.assertEqual(manifest.lanes, ())

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
        store.persist(handle, manifest)
        store.persist(handle, manifest)

        manifest_row = connection.execute("select manifest_json from team_runtime_manifests where team_id = 'product'").fetchone()
        lane_rows = connection.execute("select lane_id, kind from team_runtime_lanes order by lane_id").fetchall()

        self.assertEqual(json.loads(manifest_row[0])["team_id"], "product")
        self.assertEqual(
            lane_rows,
            [
                ("entrypoint:entry", "entrypoint"),
                ("relation:entry:ask_worker:worker", "tool-relation"),
            ],
        )
        handle.close()


if __name__ == "__main__":
    unittest.main()
