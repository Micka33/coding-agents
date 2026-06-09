from __future__ import annotations

from collections.abc import Iterable
from pathlib import Path

from src.type_defs import is_json_object
from src.team_loader.models.team_definition import TeamDefinition
from src.team_loader.errors.team_loader_error import TeamLoaderError
from src.team_loader.resolvers.working_directory_resolver import WorkingDirectoryResolver


class TeamValidator:
    def __init__(self, working_directory_resolver: WorkingDirectoryResolver | None = None) -> None:
        self._working_directory_resolver = working_directory_resolver or WorkingDirectoryResolver()

    def validate(self, team: TeamDefinition) -> None:
        self._validate_schema(team)
        self._validate_working_directories(team)
        self._validate_custom_tools(team)
        self._validate_mcp_servers(team)
        self._validate_toolsets(team)
        self._validate_agents(team)
        self._validate_relations(team)
        self._validate_conversation(team)

    def _validate_schema(self, team: TeamDefinition) -> None:
        if team.schema_version != 1:
            raise TeamLoaderError(f"Unsupported team schema_version: {team.schema_version!r}.")
        if not team.id:
            raise TeamLoaderError("team.yaml requires a non-empty id.")
        defaults = team.raw.get("defaults") if is_json_object(getattr(team, "raw", None)) else None
        if is_json_object(defaults):
            allowed = {"model", "reasoning_effort", "checkpointer", "execution_backend", "memory"}
            unsupported = sorted(key for key in defaults if key not in allowed)
            if unsupported:
                raise TeamLoaderError(f"defaults contains unsupported key: {unsupported[0]}.")

    def _validate_working_directories(self, team: TeamDefinition) -> None:
        working_directory = str(getattr(team, "working_directory", "."))
        if not working_directory:
            raise TeamLoaderError("team.yaml working_directory must not be empty.")
        team_directory = self._working_directory_resolver.resolve_team(team)
        if not team_directory.is_dir():
            raise TeamLoaderError(f"team.yaml working_directory must be an existing directory: {team_directory}")
        for agent_id, agent in getattr(team, "agents", {}).items():
            configured = str(getattr(agent, "relative_working_directory", "."))
            if not configured:
                raise TeamLoaderError(f"agents.{agent_id}.relative_working_directory must not be empty.")
            if Path(configured).is_absolute():
                raise TeamLoaderError(f"agents.{agent_id}.relative_working_directory must be relative.")
            try:
                agent_directory = self._working_directory_resolver.resolve_agent(team, agent)
            except ValueError as error:
                raise TeamLoaderError(
                    f"agents.{agent_id}.relative_working_directory must stay within team working_directory."
                ) from error
            if not agent_directory.is_dir():
                raise TeamLoaderError(
                    f"agents.{agent_id}.relative_working_directory must be an existing directory: {agent_directory}"
                )

    def _validate_custom_tools(self, team: TeamDefinition) -> None:
        for custom_tool in team.custom_tools.values():
            if ":" not in custom_tool.factory:
                raise TeamLoaderError(f"custom_tools.{custom_tool.id}.factory must use module:function format.")
            if not custom_tool.exposes:
                raise TeamLoaderError(f"custom_tools.{custom_tool.id}.exposes must list at least one tool.")

    def _validate_mcp_servers(self, team: TeamDefinition) -> None:
        for server in getattr(team, "mcp_servers", {}).values():
            if server.transport not in {"stdio", "streamable_http", "sse"}:
                raise TeamLoaderError(f"mcp_servers.{server.id}.transport must be stdio, http, streamable_http, or sse.")
            if server.exposes == ():
                raise TeamLoaderError(f"mcp_servers.{server.id}.exposes must list at least one tool when configured.")
            if server.timeout is not None and server.timeout < 1:
                raise TeamLoaderError(f"mcp_servers.{server.id}.timeout must be positive.")
            if server.auth is not None:
                self._validate_mcp_auth(server.id, server.auth)
            if server.transport == "stdio":
                if server.auth is not None:
                    raise TeamLoaderError(f"mcp_servers.{server.id}.auth is supported only for HTTP transports.")
                if not server.command:
                    raise TeamLoaderError(f"mcp_servers.{server.id}.command is required for stdio transport.")
                continue
            if not server.url:
                raise TeamLoaderError(f"mcp_servers.{server.id}.url is required for {server.transport} transport.")

    def _validate_mcp_auth(self, server_id: str, auth: object) -> None:
        auth_type = str(getattr(auth, "type", ""))
        if auth_type not in {"bearer", "api_key", "custom"}:
            raise TeamLoaderError(f"mcp_servers.{server_id}.auth.type must be bearer, api_key, or custom.")
        if auth_type == "bearer" and not getattr(auth, "env", None):
            raise TeamLoaderError(f"mcp_servers.{server_id}.auth.env is required for bearer auth.")
        if auth_type == "api_key":
            if not getattr(auth, "header", None):
                raise TeamLoaderError(f"mcp_servers.{server_id}.auth.header is required for api_key auth.")
            if not getattr(auth, "env", None):
                raise TeamLoaderError(f"mcp_servers.{server_id}.auth.env is required for api_key auth.")
        if auth_type == "custom":
            factory = str(getattr(auth, "factory", "") or "")
            if ":" not in factory:
                raise TeamLoaderError(f"mcp_servers.{server_id}.auth.factory must use module:function format.")

    def _validate_toolsets(self, team: TeamDefinition) -> None:
        for toolset in team.toolsets.values():
            if not toolset.tools:
                raise TeamLoaderError(f"toolsets.{toolset.name} must list at least one tool.")
            for tool in toolset.tools:
                custom = getattr(tool, "custom", None)
                mcp = getattr(tool, "mcp", None)
                if custom and custom not in team.custom_tools:
                    raise TeamLoaderError(f"toolsets.{toolset.name} references unknown custom tool '{custom}'.")
                if mcp and mcp not in getattr(team, "mcp_servers", {}):
                    raise TeamLoaderError(f"toolsets.{toolset.name} references unknown MCP server '{mcp}'.")

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
