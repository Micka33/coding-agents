from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from src.type_defs import JsonObject, JsonValue
from src.team_loader.models._coercion import optional_string, string_tuple
from src.team_loader.models.agent_reference import AgentReference
from src.team_loader.models.agent_state import AgentState
from src.team_loader.models.mdc_document import MdcDocument


@dataclass(frozen=True)
class AgentDefinition:
    id: str
    kind: str
    config_path: Path
    relative_working_directory: str
    entrypoint: bool
    enable_general_purpose_subagent: bool
    description: str | None
    model: str | None
    reasoning_effort: str | None
    variables: JsonObject
    toolsets: tuple[str, ...]
    state: AgentState
    skills: JsonValue
    memory: JsonValue
    debug: JsonValue
    prompt: str
    frontmatter: JsonObject

    @classmethod
    def from_document(
        cls,
        reference: AgentReference,
        document: MdcDocument,
        prompt: str,
        variables: JsonObject,
    ) -> AgentDefinition:
        data = document.frontmatter
        return cls(
            id=reference.id,
            kind=reference.kind,
            config_path=document.path,
            relative_working_directory=reference.relative_working_directory,
            entrypoint=reference.entrypoint,
            enable_general_purpose_subagent=reference.enable_general_purpose_subagent,
            description=optional_string(data.get("description")),
            model=optional_string(data.get("model")) or "inherit",
            reasoning_effort=optional_string(data.get("reasoning_effort")) or "inherit",
            variables=dict(variables),
            toolsets=string_tuple(data.get("toolsets")),
            state=AgentState.from_mapping(data.get("state")),
            skills=data.get("skills", "inherit"),
            memory=data.get("memory", "inherit"),
            debug=data.get("debug", "inherit"),
            prompt=prompt,
            frontmatter=dict(data),
        )
