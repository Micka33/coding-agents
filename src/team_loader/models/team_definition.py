from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, replace
from pathlib import Path

from src.type_defs import JsonObject
from src.team_loader.models._coercion import as_json_object, int_value, optional_string, string_value
from src.team_loader.models.agent_definition import AgentDefinition
from src.team_loader.models.agent_reference import AgentReference
from src.team_loader.models.human_input_settings import HumanInputSettings
from src.team_loader.models.team_conversation_settings import TeamConversationSettings
from src.team_loader.models.custom_tool_definition import CustomToolDefinition
from src.team_loader.models.mcp_server_definition import McpServerDefinition
from src.team_loader.models.relation_definition import RelationDefinition
from src.team_loader.models.team_defaults import TeamDefaults
from src.team_loader.models.toolset_definition import ToolsetDefinition


@dataclass(frozen=True)
class TeamDefinition:
    path: Path
    load_cwd: Path
    schema_version: int
    id: str
    description: str | None
    working_directory: str
    defaults: TeamDefaults
    custom_tools: dict[str, CustomToolDefinition]
    mcp_servers: dict[str, McpServerDefinition]
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
        load_cwd: Path | None = None,
    ) -> TeamDefinition:
        defaults = TeamDefaults.from_mapping(mapping.get("defaults"))
        custom_tools = {
            key: CustomToolDefinition.from_mapping(key, value)
            for key, value in as_json_object(mapping.get("custom_tools")).items()
        }
        mcp_servers = {
            key: McpServerDefinition.from_mapping(key, value)
            for key, value in as_json_object(mapping.get("mcp_servers")).items()
        }
        toolsets = {
            key: ToolsetDefinition.from_sequence(key, value)
            for key, value in as_json_object(mapping.get("toolsets")).items()
        }
        agent_references = {
            key: AgentReference.from_mapping(key, value)
            for key, value in as_json_object(mapping.get("agents")).items()
        }
        agent_id_lookup = cls._case_insensitive_lookup(agent_references)
        raw_relations = mapping.get("relations")
        relations = tuple(
            cls._canonical_relation(RelationDefinition.from_mapping(item), agent_id_lookup, index)
            for index, item in enumerate(raw_relations if isinstance(raw_relations, list) else ())
        )
        conversation = (
            TeamConversationSettings.from_mapping(mapping.get("conversation"))
            if "conversation" in mapping
            else None
        )
        if conversation is not None:
            participant_lookup = cls._case_insensitive_lookup(
                agent_id
                for agent_id, reference in agent_references.items()
                if reference.conversation is not None
            )
            conversation = cls._canonical_conversation(conversation, participant_lookup)
        return cls(
            path=path,
            load_cwd=(load_cwd or Path.cwd()).resolve(),
            schema_version=int_value(mapping.get("schema_version"), 0),
            id=string_value(mapping.get("id")),
            description=optional_string(mapping.get("description")),
            working_directory=string_value(mapping.get("working_directory"), "."),
            defaults=defaults,
            custom_tools=custom_tools,
            mcp_servers=mcp_servers,
            toolsets=toolsets,
            agent_references=agent_references,
            agents=agents,
            relations=relations,
            conversation=conversation,
            raw=mapping,
        )

    def entrypoint(self) -> AgentDefinition | None:
        for agent in self.agents.values():
            if agent.entrypoint:
                return agent
        return None

    def template_variables(self) -> dict[str, str]:
        return {"working_directory": self.working_directory}

    @staticmethod
    def _case_insensitive_lookup(agent_ids: Iterable[str]) -> dict[str, str]:
        lookup: dict[str, str] = {}
        duplicates: set[str] = set()
        for agent_id in agent_ids:
            normalized = str(agent_id).casefold()
            previous = lookup.get(normalized)
            if previous is not None and previous != agent_id:
                duplicates.add(normalized)
            else:
                lookup[normalized] = str(agent_id)
        for duplicate in duplicates:
            lookup.pop(duplicate, None)
        return lookup

    @classmethod
    def _canonical_relation(
        cls,
        relation: RelationDefinition,
        agent_id_lookup: dict[str, str],
        index: int = 0,
    ) -> RelationDefinition:
        return replace(
            relation,
            id=relation.id or f"relation_{index + 1:03d}",
            source=cls._canonical_agent_id(relation.source, agent_id_lookup),
            target=cls._canonical_agent_id(relation.target, agent_id_lookup),
        )

    @classmethod
    def _canonical_conversation(
        cls,
        conversation: TeamConversationSettings,
        participant_lookup: dict[str, str],
    ) -> TeamConversationSettings:
        default_targets = tuple(
            cls._canonical_agent_id(target, participant_lookup)
            for target in conversation.human_input.default_targets
        )
        return replace(
            conversation,
            human_input=HumanInputSettings(default_targets=default_targets),
        )

    @staticmethod
    def _canonical_agent_id(agent_id: str, agent_id_lookup: dict[str, str]) -> str:
        return agent_id_lookup.get(agent_id.casefold(), agent_id)
