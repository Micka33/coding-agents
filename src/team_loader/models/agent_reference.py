from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from src.type_defs import JsonObject
from src.team_loader.models._coercion import as_json_object, string_value
from src.team_loader.models.agent_conversation_settings import AgentConversationSettings

# Keys that describe team topology and live only in the team.yaml agent entry.
REFERENCE_KEYS = frozenset(
    {
        "kind",
        "config",
        "relative_working_directory",
        "entrypoint",
        "enable_general_purpose_subagent",
        "conversation",
    }
)
# Agent-local config keys that may appear in the agent entry to override the
# matching `.mdc` frontmatter value.
OVERRIDE_KEYS = frozenset(
    {
        "description",
        "model",
        "reasoning_effort",
        "variables",
        "toolsets",
        "state",
        "skills",
        "memory",
        "debug",
    }
)


@dataclass(frozen=True)
class AgentReference:
    id: str
    kind: str
    config: str
    relative_working_directory: str
    entrypoint: bool
    enable_general_purpose_subagent: bool = False
    conversation: AgentConversationSettings | None = None
    overrides: JsonObject = field(default_factory=dict)

    @classmethod
    def from_mapping(cls, agent_id: str, value: object) -> AgentReference:
        mapping = as_json_object(value)
        conversation = (
            AgentConversationSettings.from_mapping(mapping.get("conversation"))
            if "conversation" in mapping
            else None
        )
        overrides = {key: mapping[key] for key in mapping if key in OVERRIDE_KEYS}
        return cls(
            id=agent_id,
            kind=string_value(mapping.get("kind")),
            config=string_value(mapping.get("config")),
            relative_working_directory=string_value(mapping.get("relative_working_directory"), "."),
            entrypoint=bool(mapping.get("entrypoint", False)),
            enable_general_purpose_subagent=bool(
                mapping.get("enable_general_purpose_subagent", False)
            ),
            conversation=conversation,
            overrides=overrides,
        )

    def config_path(self, team_file: Path) -> Path:
        return (team_file.parent / self.config).resolve()
