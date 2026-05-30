from __future__ import annotations

import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from src.team_instanciator.runtime_configuration import RuntimeConfiguration
from src.team_instanciator.team_instanciator import TeamInstanciator
from tests.support import agent, defaults, team


class Loader:
    def __init__(self, loaded_team) -> None:
        self.loaded_team = loaded_team
        self.calls = []

    def load(self, team_file, variables):
        self.calls.append((team_file, variables))
        return self.loaded_team


class ClosableCheckpointer:
    def __init__(self) -> None:
        self.checkpointer = "checkpointer"
        self.connection = None
        self.closed = False

    def close(self) -> None:
        self.closed = True


class FakeCheckpointerFactory:
    handle = ClosableCheckpointer()

    def __init__(self, configuration) -> None:
        self.configuration = configuration

    def create(self, team_config):
        return self.__class__.handle


class FakeRegistry:
    graph_exception: Exception | None = None
    graph_calls: list[str] = []

    def __init__(self, *args) -> None:
        self.args = args

    def graph(self, agent_id: str):
        self.__class__.graph_calls.append(agent_id)
        if self.__class__.graph_exception is not None:
            raise self.__class__.graph_exception
        return SimpleNamespace(id=f"graph:{agent_id}")


class TeamInstanciatorTests(unittest.TestCase):
    def setUp(self) -> None:
        FakeCheckpointerFactory.handle = ClosableCheckpointer()
        FakeRegistry.graph_exception = None
        FakeRegistry.graph_calls = []

    def test_instantiate_builds_entrypoint_graph_and_runtime_manifest(self) -> None:
        loaded_team = team(
            team_id="product",
            agents={"entry": agent("entry", entrypoint=True)},
            team_defaults=defaults(root_dir=Path.cwd()),
        )
        loader = Loader(loaded_team)

        with (
            patch("src.team_instanciator.team_instanciator.CheckpointerFactory", FakeCheckpointerFactory),
            patch("src.team_instanciator.team_instanciator.AgentGraphRegistry", FakeRegistry),
        ):
            instantiated = TeamInstanciator(loader, config_variables={"BASE": "one"}).instantiate("team.yaml", {"topic": "ai"}, {"EXTRA": "two"})

        self.assertEqual(loader.calls, [("team.yaml", {"topic": "ai"})])
        self.assertEqual(FakeRegistry.graph_calls, ["entry"])
        self.assertEqual(instantiated.team, loaded_team)
        self.assertEqual(instantiated.graph.id, "graph:entry")
        self.assertFalse(FakeCheckpointerFactory.handle.closed)
        self.assertEqual(instantiated.runtime_manifest.team_id, "product")

    def test_instantiate_closes_checkpointer_when_team_has_no_entrypoint(self) -> None:
        loaded_team = team(agents={"worker": agent("worker")}, team_defaults=defaults(root_dir=Path.cwd()))

        with (
            patch("src.team_instanciator.team_instanciator.CheckpointerFactory", FakeCheckpointerFactory),
            patch("src.team_instanciator.team_instanciator.AgentGraphRegistry", FakeRegistry),
            self.assertRaisesRegex(ValueError, "no entrypoint"),
        ):
            TeamInstanciator(Loader(loaded_team)).instantiate("team.yaml")

        self.assertTrue(FakeCheckpointerFactory.handle.closed)

    def test_instantiate_closes_checkpointer_when_graph_creation_fails(self) -> None:
        loaded_team = team(agents={"entry": agent("entry", entrypoint=True)}, team_defaults=defaults(root_dir=Path.cwd()))
        FakeRegistry.graph_exception = RuntimeError("boom")

        with (
            patch("src.team_instanciator.team_instanciator.CheckpointerFactory", FakeCheckpointerFactory),
            patch("src.team_instanciator.team_instanciator.AgentGraphRegistry", FakeRegistry),
            self.assertRaisesRegex(RuntimeError, "boom"),
        ):
            TeamInstanciator(Loader(loaded_team)).instantiate("team.yaml")

        self.assertTrue(FakeCheckpointerFactory.handle.closed)

    def test_runtime_configuration_instance_is_reused(self) -> None:
        configuration = RuntimeConfiguration({"VALUE": "one"})

        instanciator = TeamInstanciator(config_variables=configuration)

        self.assertIs(instanciator._configuration, configuration)


if __name__ == "__main__":
    unittest.main()
