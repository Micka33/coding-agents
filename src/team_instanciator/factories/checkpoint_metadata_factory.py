from __future__ import annotations

from src.team_loader.models.agent_definition import AgentDefinition
from src.team_loader.models.relation_definition import RelationDefinition
from src.team_loader.models.team_definition import TeamDefinition


class CheckpointMetadataFactory:
    def __init__(self) -> None:
        from src.team_instanciator.runtime.thread_id_factory import ThreadIdFactory

        self._thread_id_factory = ThreadIdFactory()

    def entrypoint(self, team: TeamDefinition, agent: AgentDefinition) -> dict[str, str]:
        return self._agent_metadata(team, agent, "entrypoint", f"entrypoint:{agent.id}")

    def direct_agent(self, team: TeamDefinition, agent: AgentDefinition) -> dict[str, str]:
        return self._agent_metadata(team, agent, "agent", f"agent:{agent.id}")

    def tool_relation(self, team: TeamDefinition, relation: RelationDefinition) -> dict[str, str]:
        target = team.agents[relation.target]
        tool_name = relation.tool_name or relation.relation
        relation_id = self._thread_id_factory.relation_id(relation)
        metadata = self._agent_metadata(
            team,
            target,
            "tool-relation",
            f"relation:{relation_id}",
        )
        metadata.update(
            {
                "relation_id": relation_id,
                "source_agent_id": relation.source,
                "target_agent_id": relation.target,
                "tool_name": tool_name,
            }
        )
        return metadata

    def mention(self, team: TeamDefinition, agent: AgentDefinition) -> dict[str, str]:
        metadata = self._agent_metadata(team, agent, "mention", f"mention:{agent.id}")
        metadata.update({"target_agent_id": agent.id})
        return metadata

    def task_subagent_type(self, team: TeamDefinition, agent: AgentDefinition) -> dict[str, str]:
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
    ) -> dict[str, str]:
        return {
            "team_id": team.id,
            "agent_id": agent.id,
            "agent_name": agent.id,
            "thread_kind": thread_kind,
            "lane_id": lane_id,
        }
