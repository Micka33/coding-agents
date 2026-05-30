from __future__ import annotations

from dataclasses import dataclass

from src.team_loader.models._coercion import as_json_object, int_value
from src.team_loader.models.human_input_settings import HumanInputSettings
from src.team_loader.models.mention_settings import MentionSettings


@dataclass(frozen=True)
class TeamConversationSettings:
    mentions: MentionSettings
    human_input: HumanInputSettings
    identity_refresh_after_tokens: int = 10_000

    @classmethod
    def from_mapping(cls, value: object) -> TeamConversationSettings:
        mapping = as_json_object(value)
        return cls(
            mentions=MentionSettings.from_mapping(mapping.get("mentions")),
            human_input=HumanInputSettings.from_mapping(mapping.get("human_input")),
            identity_refresh_after_tokens=int_value(mapping.get("identity_refresh_after_tokens"), 10_000),
        )
