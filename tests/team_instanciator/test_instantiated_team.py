from __future__ import annotations

import unittest

from src.team_instanciator.core.instantiated_team import InstantiatedTeam
from tests.support import FakeClosable, FakeGraph, team


class InstantiatedTeamTests(unittest.TestCase):
    def test_delegates_invocation_context_management_close_and_attribute_access(self) -> None:
        graph = FakeGraph({"ok": True})
        handle = FakeClosable()
        instantiated = InstantiatedTeam(team(), graph, handle, runtime_manifest="manifest")

        self.assertEqual(instantiated.invoke("input", key="value"), {"ok": True})
        self.assertEqual(graph.calls[0], ("input", None, {"key": "value"}))
        self.assertEqual(instantiated.extra, "extra-value")

        with instantiated as entered:
            self.assertIs(entered, instantiated)

        self.assertTrue(handle.closed)

    def test_conversation_for_returns_none_default_or_requested_thread(self) -> None:
        default_conversation = object()
        requested_conversation = object()
        conversation = FakeGraph(default_conversation)
        conversation.with_conversation_id = lambda conversation_id: requested_conversation

        without_conversation = InstantiatedTeam(team(), FakeGraph(), FakeClosable(), runtime_manifest="manifest")
        with_conversation = InstantiatedTeam(
            team(),
            FakeGraph(),
            FakeClosable(),
            runtime_manifest="manifest",
            conversation=conversation,
        )

        self.assertIsNone(without_conversation.conversation_for("thread"))
        self.assertIs(with_conversation.conversation_for(None), conversation)
        self.assertIs(with_conversation.conversation_for("thread"), requested_conversation)


if __name__ == "__main__":
    unittest.main()
