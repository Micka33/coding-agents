from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import Any


class FakeTeam(SimpleNamespace):
    def entrypoint(self) -> Any:
        for agent in self.agents.values():
            if getattr(agent, "entrypoint", False):
                return agent
        return None


class FakeGraph:
    def __init__(self, result: Any | None = None) -> None:
        self.calls: list[tuple[Any, Any, dict[str, Any]]] = []
        self.result = result if result is not None else {"messages": []}
        self.extra = "extra-value"

    def invoke(self, input: Any, config: Any = None, **kwargs: Any) -> Any:
        self.calls.append((input, config, kwargs))
        return self.result


class FakeClosable:
    def __init__(self) -> None:
        self.closed = False

    def close(self) -> None:
        self.closed = True


def defaults(
    *,
    root_dir: str | Path = ".",
    model_env: str | None = None,
    model_default: str | None = "openai:gpt-test",
    reasoning_env: str | None = None,
    reasoning_default: str | None = None,
    checkpointer_env: str | None = None,
    checkpointer_default: str | None = "memory",
    sqlite_path_env: str | None = None,
    sqlite_path_default: str | None = None,
    execution_backend_env: str | None = None,
    execution_backend_default: str | None = "none",
    memory_candidates: tuple[Any, ...] = (),
    memory_error_when_missing: bool = False,
) -> SimpleNamespace:
    return SimpleNamespace(
        root_dir=str(root_dir),
        model=SimpleNamespace(env=model_env, default=model_default),
        reasoning_effort=SimpleNamespace(env=reasoning_env, default=reasoning_default),
        checkpointer=SimpleNamespace(
            env=checkpointer_env,
            default=checkpointer_default,
            sqlite_path_env=sqlite_path_env,
            sqlite_path_default=sqlite_path_default,
        ),
        execution_backend=SimpleNamespace(env=execution_backend_env, default=execution_backend_default),
        memory=SimpleNamespace(candidates=memory_candidates, error_when_missing=memory_error_when_missing),
    )


def agent(
    agent_id: str = "agent",
    *,
    kind: str = "deepagent",
    entrypoint: bool = False,
    toolsets: tuple[str, ...] = (),
    model: str | None = "inherit",
    reasoning_effort: str | None = "inherit",
    description: str | None = None,
    prompt: str = "Prompt",
    state_persistence: str = "inherit",
    skills: Any = "inherit",
    memory: Any = "inherit",
    debug: Any = "inherit",
    config_path: Path | None = None,
) -> SimpleNamespace:
    return SimpleNamespace(
        id=agent_id,
        kind=kind,
        entrypoint=entrypoint,
        toolsets=toolsets,
        model=model,
        reasoning_effort=reasoning_effort,
        description=description,
        prompt=prompt,
        state=SimpleNamespace(persistence=state_persistence),
        skills=skills,
        memory=memory,
        debug=debug,
        config_path=config_path or Path(f"{agent_id}.mdc"),
    )


def relation(
    *,
    source: str = "entry",
    target: str = "worker",
    relation_type: str = "tool",
    tool_name: str | None = "ask_worker",
    description: str | None = None,
) -> SimpleNamespace:
    return SimpleNamespace(
        source=source,
        target=target,
        relation=relation_type,
        tool_name=tool_name,
        description=description,
    )


def team(
    *,
    team_id: str = "team",
    agents: dict[str, Any] | None = None,
    relations: tuple[Any, ...] = (),
    team_defaults: Any | None = None,
    custom_tools: dict[str, Any] | None = None,
    toolsets: dict[str, Any] | None = None,
    agent_references: dict[str, Any] | None = None,
    schema_version: int = 1,
    conversation: Any | None = None,
) -> FakeTeam:
    resolved_agents = agents or {"entry": agent("entry", entrypoint=True)}
    return FakeTeam(
        id=team_id,
        schema_version=schema_version,
        defaults=team_defaults or defaults(),
        agents=resolved_agents,
        relations=relations,
        custom_tools=custom_tools or {},
        toolsets=toolsets or {},
        agent_references=agent_references if agent_references is not None else resolved_agents,
        conversation=conversation,
        path=Path("team.yaml"),
        raw={},
    )
