from __future__ import annotations

from typing import Any

from coding_agents.team_loader.agent_definition import AgentDefinition
from coding_agents.team_loader.relation_definition import RelationDefinition
from coding_agents.team_loader.team_definition import TeamDefinition


class CheckpointMetadataFactory:
    def entrypoint(self, team: TeamDefinition, agent: AgentDefinition) -> dict[str, Any]:
        return self._agent_metadata(team, agent, "entrypoint", f"entrypoint:{agent.id}")

    def direct_agent(self, team: TeamDefinition, agent: AgentDefinition) -> dict[str, Any]:
        return self._agent_metadata(team, agent, "agent", f"agent:{agent.id}")

    def tool_relation(self, team: TeamDefinition, relation: RelationDefinition) -> dict[str, Any]:
        target = team.agents[relation.target]
        tool_name = relation.tool_name or relation.relation
        metadata = self._agent_metadata(
            team,
            target,
            "tool-relation",
            f"relation:{relation.source}:{tool_name}:{relation.target}",
        )
        metadata.update(
            {
                "source_agent_id": relation.source,
                "target_agent_id": relation.target,
                "tool_name": tool_name,
            }
        )
        return metadata

    def task_subagent_type(self, team: TeamDefinition, agent: AgentDefinition) -> dict[str, Any]:
        return self._agent_metadata(
            team,
            agent,
            "task-subagent",
            f"task-subagent-type:{agent.id}",
        )

    def _agent_metadata(
        self,
        team: TeamDefinition,
        agent: AgentDefinition,
        thread_kind: str,
        lane_id: str,
    ) -> dict[str, Any]:
        return {
            "team_id": team.id,
            "agent_id": agent.id,
            "agent_name": agent.name,
            "thread_kind": thread_kind,
            "lane_id": lane_id,
        }
