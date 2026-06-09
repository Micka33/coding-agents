from __future__ import annotations

from dataclasses import dataclass

from src.team_loader.models.team_definition import TeamDefinition

from src.team_instanciator.core.agent_graph import AgentGraph
from src.team_instanciator.runtime.checkpointer_handle import CheckpointerHandle
from src.team_instanciator.conversation import MentionAwareTeam
from src.team_instanciator.manifest.team_runtime_manifest import TeamRuntimeManifest


@dataclass
class InstantiatedTeam:
    team: TeamDefinition
    graph: AgentGraph
    checkpointer_handle: CheckpointerHandle
    runtime_manifest: TeamRuntimeManifest
    conversation: MentionAwareTeam | None = None

    def invoke(self, *args: object, **kwargs: object) -> object:
        return self.graph.invoke(*args, **kwargs)

    def conversation_for(self, conversation_id: str | None) -> MentionAwareTeam | None:
        if self.conversation is None:
            return None
        if not conversation_id:
            return self.conversation
        return self.conversation.with_conversation_id(conversation_id)

    def close(self) -> None:
        if self.conversation is not None:
            self.conversation.wait_for_idle()
        self.checkpointer_handle.close()

    def __enter__(self) -> InstantiatedTeam:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: object | None,
    ) -> None:
        self.close()

    def __getattr__(self, name: str) -> object:
        return getattr(self.graph, name)
