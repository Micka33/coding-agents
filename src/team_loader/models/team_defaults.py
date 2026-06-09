from __future__ import annotations

from dataclasses import dataclass

from src.team_loader.models._coercion import as_json_object
from src.team_loader.models.checkpointer_default import CheckpointerDefault
from src.team_loader.models.execution_backend_default import ExecutionBackendDefault
from src.team_loader.models.memory_default import MemoryDefault
from src.team_loader.models.model_default import ModelDefault
from src.team_loader.models.reasoning_effort_default import ReasoningEffortDefault


@dataclass(frozen=True)
class TeamDefaults:
    model: ModelDefault
    reasoning_effort: ReasoningEffortDefault
    checkpointer: CheckpointerDefault
    execution_backend: ExecutionBackendDefault
    memory: MemoryDefault

    @classmethod
    def from_mapping(cls, value: object) -> TeamDefaults:
        mapping = as_json_object(value)
        return cls(
            model=ModelDefault.from_mapping(mapping.get("model")),
            reasoning_effort=ReasoningEffortDefault.from_mapping(mapping.get("reasoning_effort")),
            checkpointer=CheckpointerDefault.from_mapping(mapping.get("checkpointer")),
            execution_backend=ExecutionBackendDefault.from_mapping(mapping.get("execution_backend")),
            memory=MemoryDefault.from_mapping(mapping.get("memory")),
        )
