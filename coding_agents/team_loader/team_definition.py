from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .agent_definition import AgentDefinition
from .agent_reference import AgentReference
from .custom_tool_definition import CustomToolDefinition
from .relation_definition import RelationDefinition
from .team_defaults import TeamDefaults
from .toolset_definition import ToolsetDefinition


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
    raw: dict[str, Any]

    @classmethod
    def from_mapping(
        cls,
        path: Path,
        mapping: dict[str, Any],
        agents: dict[str, AgentDefinition],
    ) -> TeamDefinition:
        custom_tools = {
            key: CustomToolDefinition.from_mapping(key, value)
            for key, value in (mapping.get("custom_tools") or {}).items()
        }
        toolsets = {
            key: ToolsetDefinition.from_sequence(key, value)
            for key, value in (mapping.get("toolsets") or {}).items()
        }
        agent_references = {
            key: AgentReference.from_mapping(key, value)
            for key, value in (mapping.get("agents") or {}).items()
        }
        relations = tuple(RelationDefinition.from_mapping(item) for item in (mapping.get("relations") or ()))
        return cls(
            path=path,
            schema_version=mapping.get("schema_version", 0),
            id=mapping.get("id", ""),
            description=mapping.get("description"),
            defaults=TeamDefaults.from_mapping(mapping.get("defaults")),
            custom_tools=custom_tools,
            toolsets=toolsets,
            agent_references=agent_references,
            agents=agents,
            relations=relations,
            raw=mapping,
        )

    def entrypoint(self) -> AgentDefinition | None:
        for agent in self.agents.values():
            if agent.entrypoint:
                return agent
        return None
