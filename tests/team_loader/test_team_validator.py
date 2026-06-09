from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from src.team_loader.errors.team_loader_error import TeamLoaderError
from src.team_loader.models.mcp_server_definition import McpServerDefinition
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
        "mcp_servers": {},
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
        self.assert_invalid(valid_team(raw={"defaults": {"extra": "."}}), "unsupported key")
        self.assert_invalid(valid_team(custom_tools={"probe": SimpleNamespace(id="probe", factory="module", exposes=("tool",))}), "module:function")
        self.assert_invalid(valid_team(custom_tools={"probe": SimpleNamespace(id="probe", factory="module:function", exposes=())}), "exposes")
        self.assert_invalid(valid_team(toolsets={"empty": SimpleNamespace(name="empty", tools=())}), "must list")
        self.assert_invalid(
            valid_team(toolsets={"custom": SimpleNamespace(name="custom", tools=(SimpleNamespace(custom="missing"),))}),
            "unknown custom tool",
        )
        time_server = McpServerDefinition.from_mapping("time", {"transport": "stdio", "command": "uvx"})
        TeamValidator().validate(
            valid_team(
                mcp_servers={"time": time_server},
                toolsets={"time": SimpleNamespace(name="time", tools=(SimpleNamespace(custom=None, mcp="time"),))},
            )
        )
        self.assert_invalid(
            valid_team(mcp_servers={"bad": McpServerDefinition.from_mapping("bad", {"transport": "stdio"})}),
            "command is required",
        )
        self.assert_invalid(
            valid_team(mcp_servers={"bad": McpServerDefinition.from_mapping("bad", {"transport": "http"})}),
            "url is required",
        )
        self.assert_invalid(
            valid_team(mcp_servers={"bad": McpServerDefinition.from_mapping("bad", {"transport": "ftp", "url": "x"})}),
            "transport",
        )
        self.assert_invalid(
            valid_team(mcp_servers={"bad": McpServerDefinition.from_mapping("bad", {"transport": "stdio", "command": "uvx", "exposes": []})}),
            "exposes",
        )
        self.assert_invalid(
            valid_team(mcp_servers={"bad": McpServerDefinition.from_mapping("bad", {"transport": "stdio", "command": "uvx", "timeout": 0})}),
            "timeout",
        )
        self.assert_invalid(
            valid_team(
                mcp_servers={
                    "bad": McpServerDefinition.from_mapping(
                        "bad",
                        {"transport": "stdio", "command": "uvx", "auth": {"type": "bearer", "env": "TOKEN"}},
                    )
                }
            ),
            "HTTP transports",
        )
        self.assert_invalid(
            valid_team(
                mcp_servers={"docs": McpServerDefinition.from_mapping("docs", {"transport": "http", "url": "https://example.test/mcp"})},
                toolsets={"docs": SimpleNamespace(name="docs", tools=(SimpleNamespace(custom=None, mcp="missing"),))},
            ),
            "unknown MCP server",
        )
        self.assert_invalid(
            valid_team(
                mcp_servers={
                    "docs": McpServerDefinition.from_mapping(
                        "docs",
                        {"transport": "http", "url": "https://example.test/mcp", "auth": {"type": "bearer"}},
                    )
                }
            ),
            "auth.env",
        )
        self.assert_invalid(
            valid_team(
                mcp_servers={
                    "docs": McpServerDefinition.from_mapping(
                        "docs",
                        {"transport": "http", "url": "https://example.test/mcp", "auth": {"type": "api_key", "env": "KEY"}},
                    )
                }
            ),
            "auth.header",
        )
        self.assert_invalid(
            valid_team(
                mcp_servers={
                    "docs": McpServerDefinition.from_mapping(
                        "docs",
                        {"transport": "http", "url": "https://example.test/mcp", "auth": {"type": "api_key", "header": "X-Key"}},
                    )
                }
            ),
            "auth.env",
        )
        self.assert_invalid(
            valid_team(
                mcp_servers={
                    "docs": McpServerDefinition.from_mapping(
                        "docs",
                        {"transport": "http", "url": "https://example.test/mcp", "auth": {"type": "oauth"}},
                    )
                }
            ),
            "auth.type",
        )
        self.assert_invalid(
            valid_team(
                mcp_servers={
                    "docs": McpServerDefinition.from_mapping(
                        "docs",
                        {"transport": "http", "url": "https://example.test/mcp", "auth": {"type": "custom", "factory": "module"}},
                    )
                }
            ),
            "module:function",
        )

    def test_working_directory_errors(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            sub = root / "sub"
            sub.mkdir()
            TeamValidator().validate(
                valid_team(
                    working_directory=str(root),
                    load_cwd=Path.cwd(),
                    agents={"entry": agent("entry", entrypoint=True, relative_working_directory="sub")},
                )
            )
            self.assert_invalid(valid_team(working_directory="", load_cwd=Path.cwd()), "must not be empty")
            self.assert_invalid(
                valid_team(working_directory=str(root / "missing"), load_cwd=Path.cwd()),
                "working_directory",
            )
            self.assert_invalid(
                valid_team(
                    working_directory=str(root),
                    load_cwd=Path.cwd(),
                    agents={"entry": agent("entry", entrypoint=True, relative_working_directory=str(sub))},
                ),
                "must be relative",
            )
            self.assert_invalid(
                valid_team(
                    working_directory=str(root),
                    load_cwd=Path.cwd(),
                    agents={"entry": agent("entry", entrypoint=True, relative_working_directory="")},
                ),
                "relative_working_directory must not be empty",
            )
            self.assert_invalid(
                valid_team(
                    working_directory=str(root),
                    load_cwd=Path.cwd(),
                    agents={"entry": agent("entry", entrypoint=True, relative_working_directory="..")},
                ),
                "must stay within",
            )
            self.assert_invalid(
                valid_team(
                    working_directory=str(root),
                    load_cwd=Path.cwd(),
                    agents={"entry": agent("entry", entrypoint=True, relative_working_directory="missing")},
                ),
                "existing directory",
            )

    def test_skill_source_validation(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            team_file = root / "team.yaml"
            TeamValidator().validate(valid_team(path=team_file, raw={"skill_sources": ["skills", str(root / "shared")]}))
            self.assert_invalid(valid_team(path=team_file, raw={"skill_sources": "skills"}), "skill_sources")
            self.assert_invalid(valid_team(path=team_file, raw={"skill_sources": [""]}), "non-empty string")
            self.assert_invalid(valid_team(path=team_file, raw={"skill_sources": ["../shared"]}), "must stay within")

    def test_agent_errors(self) -> None:
        TeamValidator().validate(valid_team(agents={"entry": agent("entry", entrypoint=True, skills=["project"])}))
        TeamValidator().validate(valid_team(agents={"entry": agent("entry", entrypoint=True, skills={"only": ["project"]})}))
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
        self.assert_invalid(valid_team(agents={"entry": agent("entry", entrypoint=True, skills="project")}), "skills must")
        self.assert_invalid(valid_team(agents={"entry": agent("entry", entrypoint=True, skills={"except": []})}), "unsupported key")
        self.assert_invalid(valid_team(agents={"entry": agent("entry", entrypoint=True, skills={"only": "project"})}), "skills.only")
        self.assert_invalid(valid_team(agents={"entry": agent("entry", entrypoint=True, skills={"only": [1]})}), "non-empty strings")

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
