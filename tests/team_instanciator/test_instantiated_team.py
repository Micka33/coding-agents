from __future__ import annotations

import unittest

from src.team_instanciator.instantiated_team import InstantiatedTeam
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


if __name__ == "__main__":
    unittest.main()
