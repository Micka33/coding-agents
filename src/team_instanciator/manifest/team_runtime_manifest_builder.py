from __future__ import annotations

from src.team_loader.models.team_definition import TeamDefinition

from src.team_instanciator.runtime.runtime_lane import RuntimeLane
from src.team_instanciator.manifest.team_runtime_manifest import TeamRuntimeManifest
from src.team_instanciator.runtime.thread_id_factory import ThreadIdFactory


class TeamRuntimeManifestBuilder:
    def __init__(self, thread_id_factory: ThreadIdFactory | None = None) -> None:
        self._thread_id_factory = thread_id_factory or ThreadIdFactory()

    def build(self, team: TeamDefinition) -> TeamRuntimeManifest:
        lanes = [
            *self._entrypoint_lanes(team),
            *self._mention_lanes(team),
            *self._tool_relation_lanes(team),
            *self._task_subagent_type_lanes(team),
        ]
        return TeamRuntimeManifest(team_id=team.id, manifest_version=1, lanes=tuple(lanes))

    def _entrypoint_lanes(self, team: TeamDefinition) -> list[RuntimeLane]:
        entrypoint = team.entrypoint()
        if entrypoint is None:
            return []
        return [
            RuntimeLane(
                lane_id=f"entrypoint:{entrypoint.id}",
                kind="entrypoint",
                agent_id=entrypoint.id,
                agent_name=entrypoint.id,
                thread_id_pattern="{parent_thread_id}",
            )
        ]

    def _mention_lanes(self, team: TeamDefinition) -> list[RuntimeLane]:
        if getattr(team, "conversation", None) is None:
            return []
        lanes: list[RuntimeLane] = []
        for agent_id, reference in team.agent_references.items():
            if reference.conversation is None:
                continue
            agent = team.agents[agent_id]
            lanes.append(
                RuntimeLane(
                    lane_id=f"mention:{agent.id}",
                    kind="mention",
                    agent_id=agent.id,
                    agent_name=agent.id,
                    target_agent_id=agent.id,
                    thread_id_pattern=self._thread_id_factory.mention_pattern(agent.id),
                )
            )
        return lanes

    def _tool_relation_lanes(self, team: TeamDefinition) -> list[RuntimeLane]:
        lanes: list[RuntimeLane] = []
        for relation in team.relations:
            if relation.relation != "tool":
                continue
            target = team.agents[relation.target]
            tool_name = relation.tool_name or relation.relation
            lanes.append(
                RuntimeLane(
                    lane_id=f"relation:{relation.source}:{tool_name}:{relation.target}",
                    kind="tool-relation",
                    agent_id=relation.target,
                    agent_name=target.id,
                    source_agent_id=relation.source,
                    target_agent_id=relation.target,
                    tool_name=tool_name,
                    thread_id_pattern=self._thread_id_factory.relation_pattern(relation),
                )
            )
        return lanes

    def _task_subagent_type_lanes(self, team: TeamDefinition) -> list[RuntimeLane]:
        lanes: list[RuntimeLane] = []
        seen_agent_ids: set[str] = set()
        for relation in team.relations:
            if relation.relation != "subagent" or relation.target in seen_agent_ids:
                continue
            seen_agent_ids.add(relation.target)
            target = team.agents[relation.target]
            lanes.append(
                RuntimeLane(
                    lane_id=f"task-subagent-type:{relation.target}",
                    kind="task-subagent-type",
                    agent_id=relation.target,
                    agent_name=target.id,
                    target_agent_id=relation.target,
                )
            )
        return lanes
