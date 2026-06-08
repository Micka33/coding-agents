from __future__ import annotations

import unittest
from types import SimpleNamespace

from src.team_loader.errors.team_loader_error import TeamLoaderError
from src.team_loader.validation.team_validator import TeamValidator
from src.team_loader.models.conversation_settings import AgentConversationSettings, TeamConversationSettings
from tests.support import agent


def reference(
    kind: str = "deepagent",
    config: str = "entry.mdc",
    conversation=None,
    enable_general_purpose_subagent: bool = False,
) -> SimpleNamespace:
    return SimpleNamespace(
        kind=kind,
        config=config,
        conversation=conversation,
        enable_general_purpose_subagent=enable_general_purpose_subagent,
    )


def valid_team(**overrides) -> SimpleNamespace:
    data = {
        "schema_version": 1,
        "id": "product",
        "custom_tools": {},
        "toolsets": {},
        "agent_references": {"entry": reference()},
        "agents": {"entry": agent("entry", entrypoint=True)},
        "relations": (),
        "conversation": None,
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
        self.assert_invalid(
            valid_team(
                agent_references={"entry": reference(), "Entry": reference("deepagent", "other.mdc")},
                agents={"entry": agent("entry", entrypoint=True), "Entry": agent("Entry")},
            ),
            "case-insensitive",
        )
        self.assert_invalid(valid_team(agent_references={"entry": reference(kind="worker")}), "kind must be")
        self.assert_invalid(
            valid_team(agent_references={"entry": reference(kind="subagent", enable_general_purpose_subagent=True)}),
            "enable_general_purpose_subagent",
        )
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
        TeamValidator().validate(
            valid_team(
                agent_references={"Entry": reference(conversation=AgentConversationSettings())},
                agents={"Entry": agent("Entry", entrypoint=True)},
                relations=(SimpleNamespace(source="entry", target="ENTRY", relation="tool", tool_name="ask"),),
                conversation=TeamConversationSettings.from_mapping({"human_input": {"default_targets": ["ENTRY"]}}),
            )
        )
        self.assert_invalid(valid_team(relations=(SimpleNamespace(source="missing", target="entry", relation="tool", tool_name="ask"),)), "source")
        self.assert_invalid(valid_team(relations=(SimpleNamespace(source="entry", target="missing", relation="tool", tool_name="ask"),)), "target")
        self.assert_invalid(valid_team(relations=(SimpleNamespace(source="entry", target="entry", relation="peer", tool_name=None),)), "invalid type")
        self.assert_invalid(valid_team(relations=(SimpleNamespace(source="entry", target="entry", relation="tool", tool_name=None),)), "requires tool_name")
        self.assert_invalid(valid_team(relations=(SimpleNamespace(source="entry", target="entry", relation="subagent", tool_name="ask"),)), "must not define")

    def test_conversation_validation(self) -> None:
        conversation = TeamConversationSettings.from_mapping(
            {
                "mentions": {"max_parallel_agents": 2, "max_cascade_turns": None},
                "human_input": {"default_targets": ["entry"]},
            }
        )
        TeamValidator().validate(
            valid_team(
                conversation=conversation,
                agent_references={"entry": reference(conversation=AgentConversationSettings())},
            )
        )

        self.assert_invalid(
            valid_team(
                conversation=conversation,
                agent_references={"entry": reference(kind="subagent", conversation=AgentConversationSettings())},
            ),
            "kind: deepagent",
        )
        self.assert_invalid(
            valid_team(
                conversation=TeamConversationSettings.from_mapping({"human_input": {"default_targets": ["missing"]}}),
                agent_references={"entry": reference(conversation=AgentConversationSettings())},
            ),
            "non-participant",
        )
        self.assert_invalid(
            valid_team(
                conversation=TeamConversationSettings.from_mapping({"mentions": {"max_cascade_turns": 0}}),
                agent_references={"entry": reference(conversation=AgentConversationSettings())},
            ),
            "max_cascade_turns",
        )
        self.assert_invalid(
            valid_team(
                conversation=TeamConversationSettings.from_mapping({"mentions": {"max_parallel_agents": 0}}),
                agent_references={"entry": reference(conversation=AgentConversationSettings())},
            ),
            "max_parallel_agents",
        )
        self.assert_invalid(
            valid_team(
                conversation=TeamConversationSettings.from_mapping({"mentions": {"max_agent_failures": 0}}),
                agent_references={"entry": reference(conversation=AgentConversationSettings())},
            ),
            "max_agent_failures",
        )
        self.assert_invalid(
            valid_team(
                conversation=TeamConversationSettings.from_mapping({"identity_refresh_after_tokens": 0}),
                agent_references={"entry": reference(conversation=AgentConversationSettings())},
            ),
            "identity_refresh_after_tokens",
        )
        self.assert_invalid(
            valid_team(
                conversation=TeamConversationSettings.from_mapping({}),
                agent_references={"entry": reference(conversation=AgentConversationSettings(("helper", "HELPER")))},
            ),
            "duplicated",
        )
        self.assert_invalid(
            valid_team(
                conversation=TeamConversationSettings.from_mapping({}),
                agent_references={
                    "entry": reference(conversation=AgentConversationSettings(("other",))),
                    "other": reference(config="other.mdc", conversation=AgentConversationSettings()),
                },
                agents={"entry": agent("entry", entrypoint=True), "other": agent("other")},
            ),
            "conflicts",
        )
        self.assert_invalid(
            valid_team(
                conversation=TeamConversationSettings.from_mapping({}),
                agent_references={
                    "entry": reference(conversation=AgentConversationSettings(("helper",))),
                    "other": reference(config="other.mdc", conversation=AgentConversationSettings(("helper",))),
                },
                agents={"entry": agent("entry", entrypoint=True), "other": agent("other")},
            ),
            "used by both",
        )


if __name__ == "__main__":
    unittest.main()
