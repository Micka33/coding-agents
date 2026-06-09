from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from src.team_loader.models._coercion import as_json_object, string_value
from src.team_loader.models.agent_conversation_settings import AgentConversationSettings


@dataclass(frozen=True)
class AgentReference:
    id: str
    kind: str
    config: str
    relative_working_directory: str
    entrypoint: bool
    enable_general_purpose_subagent: bool = False
    conversation: AgentConversationSettings | None = None

    @classmethod
    def from_mapping(cls, agent_id: str, value: object) -> AgentReference:
        mapping = as_json_object(value)
        conversation = (
            AgentConversationSettings.from_mapping(mapping.get("conversation"))
            if "conversation" in mapping
            else None
        )
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
        )

    def config_path(self, team_file: Path) -> Path:
        return (team_file.parent / self.config).resolve()
