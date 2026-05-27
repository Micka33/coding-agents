from __future__ import annotations

from .team_definition import TeamDefinition
from .team_loader_error import TeamLoaderError


class TeamValidator:
    def validate(self, team: TeamDefinition) -> None:
        self._validate_schema(team)
        self._validate_custom_tools(team)
        self._validate_toolsets(team)
        self._validate_agents(team)
        self._validate_relations(team)

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
        entrypoints = [agent for agent in team.agents.values() if agent.entrypoint]
        if len(entrypoints) != 1:
            raise TeamLoaderError("team.yaml requires exactly one entrypoint agent.")
        for agent_id, reference in team.agent_references.items():
            if reference.kind not in {"deepagent", "subagent"}:
                raise TeamLoaderError(f"agents.{agent_id}.kind must be deepagent or subagent.")
            if not reference.config:
                raise TeamLoaderError(f"agents.{agent_id}.config is required.")
            agent = team.agents.get(agent_id)
            if agent is None:
                raise TeamLoaderError(f"Agent '{agent_id}' was not loaded.")
            if agent.id != agent_id:
                raise TeamLoaderError(f"{agent.config_path} id must match team agent id '{agent_id}'.")
            for toolset in agent.toolsets:
                if toolset not in team.toolsets:
                    raise TeamLoaderError(f"Agent '{agent_id}' references unknown toolset '{toolset}'.")
            if agent.state.persistence not in {"inherit", "disposable", "persistent"}:
                raise TeamLoaderError(f"Agent '{agent_id}' has invalid state.persistence '{agent.state.persistence}'.")

    def _validate_relations(self, team: TeamDefinition) -> None:
        for relation in team.relations:
            if relation.source not in team.agent_references:
                raise TeamLoaderError(f"Relation source '{relation.source}' is not declared in agents.")
            if relation.target not in team.agent_references:
                raise TeamLoaderError(f"Relation target '{relation.target}' is not declared in agents.")
            if relation.relation not in {"tool", "subagent"}:
                raise TeamLoaderError(f"Relation {relation.source}->{relation.target} has invalid type '{relation.relation}'.")
            if relation.relation == "tool" and not relation.tool_name:
                raise TeamLoaderError(f"Tool relation {relation.source}->{relation.target} requires tool_name.")
            if relation.relation == "subagent" and relation.tool_name:
                raise TeamLoaderError(f"Subagent relation {relation.source}->{relation.target} must not define tool_name.")
