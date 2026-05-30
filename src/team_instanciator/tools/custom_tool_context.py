from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from src.team_loader.models.agent_definition import AgentDefinition
from src.team_loader.models.team_definition import TeamDefinition

from src.team_instanciator.tools.conversation_history import ConversationHistory
from src.team_instanciator.tools.env_view import EnvView
from src.team_instanciator.configuration.runtime_configuration import RuntimeConfiguration


@dataclass(frozen=True)
class CustomToolContext:
    root_dir: Path
    env: EnvView
    runtime_config: RuntimeConfiguration
    agent_config: AgentDefinition
    team_config: TeamDefinition
    history: ConversationHistory
    checkpointer: object | None = None

    @property
    def agent(self) -> AgentDefinition:
        return self.agent_config

    @property
    def team(self) -> TeamDefinition:
        return self.team_config


__all__ = ["ConversationHistory", "CustomToolContext", "EnvView"]
