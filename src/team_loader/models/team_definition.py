from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from src.type_defs import JsonObject
from src.team_loader.models._coercion import as_json_object, int_value, optional_string, string_value
from src.team_loader.models.agent_definition import AgentDefinition
from src.team_loader.models.agent_reference import AgentReference
from src.team_loader.models.team_conversation_settings import TeamConversationSettings
from src.team_loader.models.custom_tool_definition import CustomToolDefinition
from src.team_loader.models.relation_definition import RelationDefinition
from src.team_loader.models.team_defaults import TeamDefaults
from src.team_loader.models.toolset_definition import ToolsetDefinition


@dataclass(frozen=True)
class TeamDefinition:
    path: Path
    schema_version: int
    id: str
    description: str | None
    defaults: TeamDefaults
    custom_tools: dict[str, CustomToolDefinition]
    toolsets: dict[str, ToolsetDefinition]
    agent_references: dict[str, AgentReference]
    agents: dict[str, AgentDefinition]
    relations: tuple[RelationDefinition, ...]
    conversation: TeamConversationSettings | None
    raw: JsonObject

    @classmethod
    def from_mapping(
        cls,
        path: Path,
        mapping: JsonObject,
        agents: dict[str, AgentDefinition],
    ) -> TeamDefinition:
        custom_tools = {
            key: CustomToolDefinition.from_mapping(key, value)
            for key, value in as_json_object(mapping.get("custom_tools")).items()
        }
        toolsets = {
            key: ToolsetDefinition.from_sequence(key, value)
            for key, value in as_json_object(mapping.get("toolsets")).items()
        }
        agent_references = {
            key: AgentReference.from_mapping(key, value)
            for key, value in as_json_object(mapping.get("agents")).items()
        }
        raw_relations = mapping.get("relations")
        relations = tuple(
            RelationDefinition.from_mapping(item)
            for item in (raw_relations if isinstance(raw_relations, list) else ())
        )
        return cls(
            path=path,
            schema_version=int_value(mapping.get("schema_version"), 0),
            id=string_value(mapping.get("id")),
            description=optional_string(mapping.get("description")),
            defaults=TeamDefaults.from_mapping(mapping.get("defaults")),
            custom_tools=custom_tools,
            toolsets=toolsets,
            agent_references=agent_references,
            agents=agents,
            relations=relations,
            conversation=(
                TeamConversationSettings.from_mapping(mapping.get("conversation"))
                if "conversation" in mapping
                else None
            ),
            raw=mapping,
        )

    def entrypoint(self) -> AgentDefinition | None:
        for agent in self.agents.values():
            if agent.entrypoint:
                return agent
        return None
