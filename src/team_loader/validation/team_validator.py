from __future__ import annotations

from collections.abc import Iterable

from src.team_loader.models.team_definition import TeamDefinition
from src.team_loader.errors.team_loader_error import TeamLoaderError


class TeamValidator:
    def validate(self, team: TeamDefinition) -> None:
        self._validate_schema(team)
        self._validate_custom_tools(team)
        self._validate_toolsets(team)
        self._validate_agents(team)
        self._validate_relations(team)
        self._validate_conversation(team)

    def _validate_schema(self, team: TeamDefinition) -> None:
        if team.schema_version != 1:
            raise TeamLoaderError(f"Unsupported team schema_version: {team.schema_version!r}.")
        if not team.id:
            raise TeamLoaderError("team.yaml requires a non-empty id.")

    def _validate_custom_tools(self, team: TeamDefinition) -> None:
        for custom_tool in team.custom_tools.values():
            if ":" not in custom_tool.factory:
                raise TeamLoaderError(f"custom_tools.{custom_tool.id}.factory must use module:function format.")
            if not custom_tool.exposes:
                raise TeamLoaderError(f"custom_tools.{custom_tool.id}.exposes must list at least one tool.")

    def _validate_toolsets(self, team: TeamDefinition) -> None:
        for toolset in team.toolsets.values():
            if not toolset.tools:
                raise TeamLoaderError(f"toolsets.{toolset.name} must list at least one tool.")
            for tool in toolset.tools:
                if tool.custom and tool.custom not in team.custom_tools:
                    raise TeamLoaderError(f"toolsets.{toolset.name} references unknown custom tool '{tool.custom}'.")

    def _validate_agents(self, team: TeamDefinition) -> None:
        if not team.agent_references:
            raise TeamLoaderError("team.yaml requires at least one agent.")
        agent_reference_lookup = self._case_insensitive_lookup(team.agent_references)
        if len(agent_reference_lookup) != len(team.agent_references):
            raise TeamLoaderError("Agent ids must be unique after case-insensitive normalization.")
        agent_lookup = self._case_insensitive_lookup(team.agents)
        entrypoints = [agent for agent in team.agents.values() if agent.entrypoint]
        if len(entrypoints) != 1:
            raise TeamLoaderError("team.yaml requires exactly one entrypoint agent.")
        for agent_id, reference in team.agent_references.items():
            if reference.kind not in {"deepagent", "subagent"}:
                raise TeamLoaderError(f"agents.{agent_id}.kind must be deepagent or subagent.")
            if reference.enable_general_purpose_subagent and reference.kind != "deepagent":
                raise TeamLoaderError(
                    f"agents.{agent_id}.enable_general_purpose_subagent is valid only for kind: deepagent."
                )
            if not reference.config:
                raise TeamLoaderError(f"agents.{agent_id}.config is required.")
            canonical_agent_id = agent_lookup.get(agent_id.casefold())
            agent = team.agents.get(canonical_agent_id or agent_id)
            if agent is None:
                raise TeamLoaderError(f"Agent '{agent_id}' was not loaded.")
            if agent.id.casefold() != agent_id.casefold():
                raise TeamLoaderError(f"{agent.config_path} id must match team agent id '{agent_id}'.")
            for toolset in agent.toolsets:
                if toolset not in team.toolsets:
                    raise TeamLoaderError(f"Agent '{agent_id}' references unknown toolset '{toolset}'.")
            if agent.state.persistence not in {"inherit", "disposable", "persistent"}:
                raise TeamLoaderError(f"Agent '{agent_id}' has invalid state.persistence '{agent.state.persistence}'.")

    def _validate_relations(self, team: TeamDefinition) -> None:
        agent_lookup = self._case_insensitive_lookup(team.agent_references)
        for relation in team.relations:
            if relation.source.casefold() not in agent_lookup:
                raise TeamLoaderError(f"Relation source '{relation.source}' is not declared in agents.")
            if relation.target.casefold() not in agent_lookup:
                raise TeamLoaderError(f"Relation target '{relation.target}' is not declared in agents.")
            if relation.relation not in {"tool", "subagent"}:
                raise TeamLoaderError(f"Relation {relation.source}->{relation.target} has invalid type '{relation.relation}'.")
            if relation.relation == "tool" and not relation.tool_name:
                raise TeamLoaderError(f"Tool relation {relation.source}->{relation.target} requires tool_name.")
            if relation.relation == "subagent" and relation.tool_name:
                raise TeamLoaderError(f"Subagent relation {relation.source}->{relation.target} must not define tool_name.")

    def _validate_conversation(self, team: TeamDefinition) -> None:
        if getattr(team, "conversation", None) is None:
            return

        participants = {
            agent_id
            for agent_id, reference in team.agent_references.items()
            if reference.conversation is not None
        }
        for agent_id in participants:
            reference = team.agent_references[agent_id]
            if reference.kind != "deepagent":
                raise TeamLoaderError(f"Conversation participant '{agent_id}' must be kind: deepagent.")

        mentions = team.conversation.mentions
        if mentions.max_parallel_agents < 1:
            raise TeamLoaderError("conversation.mentions.max_parallel_agents must be positive.")
        if mentions.max_cascade_turns is not None and mentions.max_cascade_turns < 1:
            raise TeamLoaderError("conversation.mentions.max_cascade_turns must be null or positive.")
        if mentions.max_agent_failures < 1:
            raise TeamLoaderError("conversation.mentions.max_agent_failures must be positive.")
        if team.conversation.identity_refresh_after_tokens < 1:
            raise TeamLoaderError("conversation.identity_refresh_after_tokens must be positive.")

        participant_lookup = self._case_insensitive_lookup(participants)
        for target in team.conversation.human_input.default_targets:
            if target.casefold() not in participant_lookup:
                raise TeamLoaderError(f"conversation.human_input.default_targets references non-participant '{target}'.")

        canonical_names = {agent_id.casefold(): agent_id for agent_id in participants}
        seen_aliases: dict[str, str] = {}
        for agent_id in participants:
            reference = team.agent_references[agent_id]
            aliases = reference.conversation.aliases if reference.conversation else ()
            local_aliases: set[str] = set()
            for alias in aliases:
                normalized = alias.casefold()
                if normalized in local_aliases:
                    raise TeamLoaderError(f"Conversation alias '{alias}' is duplicated for '{agent_id}'.")
                local_aliases.add(normalized)
                canonical_owner = canonical_names.get(normalized)
                if canonical_owner is not None and canonical_owner != agent_id:
                    raise TeamLoaderError(
                        f"Conversation alias '{alias}' for '{agent_id}' conflicts with participant '{canonical_owner}'."
                    )
                previous_owner = seen_aliases.get(normalized)
                if previous_owner is not None and previous_owner != agent_id:
                    raise TeamLoaderError(
                        f"Conversation alias '{alias}' is used by both '{previous_owner}' and '{agent_id}'."
                    )
                seen_aliases[normalized] = agent_id

    def _case_insensitive_lookup(self, values: Iterable[str]) -> dict[str, str]:
        lookup: dict[str, str] = {}
        for value in values:
            normalized = str(value).casefold()
            if normalized not in lookup:
                lookup[normalized] = str(value)
        return lookup
