from __future__ import annotations

from dataclasses import dataclass

from src.team_loader.models._coercion import as_json_object, string_tuple


@dataclass(frozen=True)
class AgentConversationSettings:
    aliases: tuple[str, ...] = ()

    @classmethod
    def from_mapping(cls, value: object) -> AgentConversationSettings:
        mapping = as_json_object(value)
        return cls(aliases=string_tuple(mapping.get("aliases")))
