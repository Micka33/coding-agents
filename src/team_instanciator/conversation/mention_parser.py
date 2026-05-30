from __future__ import annotations

import re

from src.team_loader.models.team_definition import TeamDefinition


MENTION_RE = re.compile(r"(?<![\w.])@([A-Za-z][A-Za-z0-9_-]{1,63})(?![\w.-])")


class MentionParser:
    def __init__(self, participants: set[str], aliases: dict[str, str] | None = None) -> None:
        self._participants = set(participants)
        self._lookup = {participant.casefold(): participant for participant in participants}
        for alias, agent_id in (aliases or {}).items():
            self._lookup[alias.casefold()] = agent_id

    @classmethod
    def from_team(cls, team: TeamDefinition) -> MentionParser:
        participants = {
            agent_id
            for agent_id, reference in team.agent_references.items()
            if reference.conversation is not None
        }
        aliases: dict[str, str] = {}
        for agent_id in participants:
            reference = team.agent_references[agent_id]
            for alias in reference.conversation.aliases if reference.conversation else ():
                aliases[alias] = agent_id
        return cls(participants, aliases)

    @property
    def participants(self) -> set[str]:
        return set(self._participants)

    def parse(self, content: str, *, author_id: str | None = None) -> tuple[str, ...]:
        masked = self._mask_code(content)
        mentions: list[str] = []
        seen: set[str] = set()
        for match in MENTION_RE.finditer(masked):
            agent_id = self._lookup.get(match.group(1).casefold())
            if not agent_id or agent_id == author_id or agent_id in seen:
                continue
            mentions.append(agent_id)
            seen.add(agent_id)
        return tuple(mentions)

    def _mask_code(self, content: str) -> str:
        return self._mask_inline_code(self._mask_fenced_code(content))

    def _mask_fenced_code(self, content: str) -> str:
        def replace(match: re.Match[str]) -> str:
            return " " * len(match.group(0))

        return re.sub(r"(^|\n)(`{3,}|~{3,})[^\n]*\n.*?(\n\2[ \t]*(?=\n|$)|$)", replace, content, flags=re.DOTALL)

    def _mask_inline_code(self, content: str) -> str:
        def replace(match: re.Match[str]) -> str:
            return " " * len(match.group(0))

        return re.sub(r"`+[^`\n]*`+", replace, content)
