from __future__ import annotations

import unittest

from src.team_instanciator.factories.checkpoint_metadata_factory import CheckpointMetadataFactory
from tests.support import agent, relation, team


class CheckpointMetadataFactoryTests(unittest.TestCase):
    def test_builds_entrypoint_direct_tool_relation_and_task_subagent_metadata(self) -> None:
        entry = agent("entry")
        worker = agent("worker")
        team_config = team(team_id="product", agents={"entry": entry, "worker": worker})
        factory = CheckpointMetadataFactory()

        self.assertEqual(factory.entrypoint(team_config, entry)["lane_id"], "entrypoint:entry")
        self.assertEqual(factory.direct_agent(team_config, worker)["thread_kind"], "agent")
        self.assertEqual(
            factory.mention(team_config, worker),
            {
                "team_id": "product",
                "agent_id": "worker",
                "agent_name": "worker",
                "thread_kind": "mention",
                "lane_id": "mention:worker",
                "target_agent_id": "worker",
            },
        )
        self.assertEqual(
            factory.tool_relation(team_config, relation(source="entry", target="worker", tool_name=None)),
            {
                "team_id": "product",
                "agent_id": "worker",
                "agent_name": "worker",
                "thread_kind": "tool-relation",
                "lane_id": "relation:entry:tool:worker",
                "source_agent_id": "entry",
                "target_agent_id": "worker",
                "tool_name": "tool",
            },
        )
        self.assertEqual(factory.task_subagent_type(team_config, worker)["lane_id"], "task-subagent-type:worker")


if __name__ == "__main__":
    unittest.main()
