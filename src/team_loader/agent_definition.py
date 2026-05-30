from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .agent_reference import AgentReference
from .agent_state import AgentState
from .mdc_document import MdcDocument


@dataclass(frozen=True)
class AgentDefinition:
    id: str
    name: str
    kind: str
    config_path: Path
    entrypoint: bool
    description: str | None
    model: str | None
    reasoning_effort: str | None
    variables: dict[str, Any]
    toolsets: tuple[str, ...]
    state: AgentState
    skills: Any
    memory: Any
    debug: Any
    prompt: str
    frontmatter: dict[str, Any]

    @classmethod
    def from_document(
        cls,
        reference: AgentReference,
        document: MdcDocument,
        prompt: str,
        variables: dict[str, Any],
    ) -> AgentDefinition:
        data = document.frontmatter
        return cls(
            id=reference.id,
            name=data.get("name", reference.id),
            kind=reference.kind,
            config_path=document.path,
            entrypoint=reference.entrypoint,
            description=data.get("description"),
            model=data.get("model", "inherit"),
            reasoning_effort=data.get("reasoning_effort", "inherit"),
            variables=dict(variables),
            toolsets=tuple(data.get("toolsets", ()) if isinstance(data.get("toolsets"), list) else ()),
            state=AgentState.from_mapping(data.get("state")),
            skills=data.get("skills", "inherit"),
            memory=data.get("memory", "inherit"),
            debug=data.get("debug", "inherit"),
            prompt=prompt,
            frontmatter=dict(data),
        )
