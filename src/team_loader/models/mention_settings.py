from __future__ import annotations

from dataclasses import dataclass

from src.team_loader.models._coercion import as_json_object, int_value, optional_int


@dataclass(frozen=True)
class MentionSettings:
    max_parallel_agents: int = 2
    max_cascade_turns: int | None = None
    max_agent_failures: int = 2

    @classmethod
    def from_mapping(cls, value: object) -> MentionSettings:
        mapping = as_json_object(value)
        return cls(
            max_parallel_agents=int_value(mapping.get("max_parallel_agents"), 2),
            max_cascade_turns=optional_int(mapping.get("max_cascade_turns")),
            max_agent_failures=int_value(mapping.get("max_agent_failures"), 2),
        )
