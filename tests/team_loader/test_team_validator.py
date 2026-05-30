from __future__ import annotations

import unittest
from types import SimpleNamespace

from src.team_loader.team_loader_error import TeamLoaderError
from src.team_loader.team_validator import TeamValidator
from tests.support import agent


def reference(kind: str = "deepagent", config: str = "entry.mdc") -> SimpleNamespace:
    return SimpleNamespace(kind=kind, config=config)


def valid_team(**overrides) -> SimpleNamespace:
    data = {
        "schema_version": 1,
        "id": "product",
        "custom_tools": {},
        "toolsets": {},
        "agent_references": {"entry": reference()},
        "agents": {"entry": agent("entry", entrypoint=True)},
        "relations": (),
    }
    data.update(overrides)
    return SimpleNamespace(**data)


class TeamValidatorTests(unittest.TestCase):
    def assert_invalid(self, team_config, message: str) -> None:
        with self.assertRaisesRegex(TeamLoaderError, message):
            TeamValidator().validate(team_config)

    def test_valid_team_passes(self) -> None:
        TeamValidator().validate(valid_team())

    def test_schema_custom_tool_and_toolset_errors(self) -> None:
        self.assert_invalid(valid_team(schema_version=2), "Unsupported")
        self.assert_invalid(valid_team(id=""), "non-empty id")
        self.assert_invalid(valid_team(custom_tools={"probe": SimpleNamespace(id="probe", factory="module", exposes=("tool",))}), "module:function")
        self.assert_invalid(valid_team(custom_tools={"probe": SimpleNamespace(id="probe", factory="module:function", exposes=())}), "exposes")
        self.assert_invalid(valid_team(toolsets={"empty": SimpleNamespace(name="empty", tools=())}), "must list")
        self.assert_invalid(
            valid_team(toolsets={"custom": SimpleNamespace(name="custom", tools=(SimpleNamespace(custom="missing"),))}),
            "unknown custom tool",
        )

    def test_agent_errors(self) -> None:
        self.assert_invalid(valid_team(agent_references={}, agents={}), "at least one agent")
        self.assert_invalid(valid_team(agents={"entry": agent("entry", entrypoint=False)}), "exactly one entrypoint")
        self.assert_invalid(valid_team(agent_references={"entry": reference(kind="worker")}), "kind must be")
        self.assert_invalid(valid_team(agent_references={"entry": reference(config="")}), "config is required")
        self.assert_invalid(
            valid_team(
                agent_references={"entry": reference(), "other": reference("deepagent", "other.mdc")},
                agents={"other": agent("other", entrypoint=True)},
            ),
            "was not loaded",
        )
        self.assert_invalid(valid_team(agents={"entry": agent("other", entrypoint=True)}), "id must match")
        self.assert_invalid(valid_team(agents={"entry": agent("entry", entrypoint=True, toolsets=("missing",))}), "unknown toolset")
        self.assert_invalid(valid_team(agents={"entry": agent("entry", entrypoint=True, state_persistence="forever")}), "invalid state")

    def test_relation_errors(self) -> None:
        self.assert_invalid(valid_team(relations=(SimpleNamespace(source="missing", target="entry", relation="tool", tool_name="ask"),)), "source")
        self.assert_invalid(valid_team(relations=(SimpleNamespace(source="entry", target="missing", relation="tool", tool_name="ask"),)), "target")
        self.assert_invalid(valid_team(relations=(SimpleNamespace(source="entry", target="entry", relation="peer", tool_name=None),)), "invalid type")
        self.assert_invalid(valid_team(relations=(SimpleNamespace(source="entry", target="entry", relation="tool", tool_name=None),)), "requires tool_name")
        self.assert_invalid(valid_team(relations=(SimpleNamespace(source="entry", target="entry", relation="subagent", tool_name="ask"),)), "must not define")


if __name__ == "__main__":
    unittest.main()
