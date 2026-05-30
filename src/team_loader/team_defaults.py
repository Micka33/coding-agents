from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .checkpointer_default import CheckpointerDefault
from .execution_backend_default import ExecutionBackendDefault
from .memory_default import MemoryDefault
from .model_default import ModelDefault
from .reasoning_effort_default import ReasoningEffortDefault


@dataclass(frozen=True)
class TeamDefaults:
    root_dir: str
    model: ModelDefault
    reasoning_effort: ReasoningEffortDefault
    checkpointer: CheckpointerDefault
    execution_backend: ExecutionBackendDefault
    memory: MemoryDefault

    @classmethod
    def from_mapping(cls, value: Any) -> TeamDefaults:
        mapping = value if isinstance(value, dict) else {}
        return cls(
            root_dir=mapping.get("root_dir", "."),
            model=ModelDefault.from_mapping(mapping.get("model")),
            reasoning_effort=ReasoningEffortDefault.from_mapping(mapping.get("reasoning_effort")),
            checkpointer=CheckpointerDefault.from_mapping(mapping.get("checkpointer")),
            execution_backend=ExecutionBackendDefault.from_mapping(mapping.get("execution_backend")),
            memory=MemoryDefault.from_mapping(mapping.get("memory")),
        )

    def template_variables(self) -> dict[str, str]:
        return {"root_dir": self.root_dir}
