"""Factory for the development-agent team."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from deepagents import create_deep_agent
from langchain.chat_models import init_chat_model
from langchain_core.language_models.chat_models import BaseChatModel

from coding_agents.artifacts import ensure_agent_workflow_files, validate_agent_workflow_files
from coding_agents.checkpoints import CheckpointerHandle, create_checkpointer_handle
from coding_agents.config import AgentTeamConfig
from coding_agents.env import load_dotenv_file
from coding_agents.harness import disable_default_general_purpose_subagent
from coding_agents.permissions import filesystem_permissions
from coding_agents.prompts import engineering_manager_prompt, implementation_subagents
from coding_agents.readiness import assert_readiness_approved
from coding_agents.resident_agents import create_resident_agent_team
from coding_agents.safe_filesystem import SafeFilesystemBackend, SafeLocalShellBackend
from coding_agents.scout import create_scout_subagent
from coding_agents.tools import default_tools


@dataclass
class DevelopmentTeamAgent:
    """Compiled manager graph plus owned runtime resources."""

    graph: Any
    checkpointer_handle: CheckpointerHandle

    def invoke(self, *args: Any, **kwargs: Any) -> Any:
        return self.graph.invoke(*args, **kwargs)

    def close(self) -> None:
        self.checkpointer_handle.close()

    def __enter__(self) -> DevelopmentTeamAgent:
        return self

    def __exit__(self, exc_type: Any, exc: Any, tb: Any) -> None:
        self.close()

    def __getattr__(self, name: str) -> Any:
        return getattr(self.graph, name)


def create_development_team_agent(config: AgentTeamConfig | None = None) -> DevelopmentTeamAgent:
    """Create the V0 development-agent team.

    The returned object is a LangGraph compiled graph from Deep Agents. Invoke it
    with a message payload and a config containing `configurable.thread_id`.
    """

    config = config or AgentTeamConfig()
    root_dir = config.resolved_root_dir()
    artifacts_dir = config.resolved_artifacts_dir()
    load_dotenv_file(root_dir / ".env")

    if config.initialize_artifacts:
        ensure_agent_workflow_files(root_dir, artifacts_dir)
    else:
        validate_agent_workflow_files(root_dir, artifacts_dir)

    implementation_enabled = config.mode == "implementation"
    if implementation_enabled:
        assert_readiness_approved(root_dir, artifacts_dir)

    disable_default_general_purpose_subagent(config.resolved_model())
    model = _resolve_model(config)
    disable_default_general_purpose_subagent(model)
    scout_model = _resolve_scout_model(config)
    memory = _existing_memory_files(root_dir, config.memory)
    shared_tools = default_tools()
    checkpointer_handle = create_checkpointer_handle(config)
    resident_team = create_resident_agent_team(
        model=model,
        root_dir=root_dir,
        artifacts_dir=artifacts_dir,
        parent_thread_id=config.thread_id,
        tools=shared_tools,
        memory=memory,
        checkpointer=checkpointer_handle.checkpointer,
        debug=config.debug,
    )
    manager_tools = [*shared_tools, *resident_team.manager_tools()]
    subagents = [
        create_scout_subagent(
            model=scout_model,
            root_dir=root_dir,
            tools=shared_tools,
        )
    ]
    if implementation_enabled:
        subagents.extend(implementation_subagents(shared_tools))

    backend = _resolve_backend(config, root_dir)

    manager_graph = create_deep_agent(
        name="engineering-manager",
        model=model,
        tools=manager_tools,
        system_prompt=engineering_manager_prompt(config.mode, artifacts_dir),
        subagents=subagents,
        backend=backend,
        permissions=filesystem_permissions(
            config.mode,
            artifacts_dir,
            config.implementation_write_paths,
            root_dir,
        ),
        skills=list(config.skills) or None,
        memory=list(memory) or None,
        checkpointer=checkpointer_handle.checkpointer,
        debug=config.debug,
    )
    return DevelopmentTeamAgent(manager_graph, checkpointer_handle)


def _resolve_backend(config: AgentTeamConfig, root_dir: Path) -> SafeFilesystemBackend:
    """Return the filesystem/execution backend for the manager graph."""

    execution_backend = config.resolved_execution_backend()
    if execution_backend == "local":
        return SafeLocalShellBackend(root_dir=root_dir, virtual_mode=True)
    return SafeFilesystemBackend(root_dir=root_dir, virtual_mode=True)


def _resolve_model(config: AgentTeamConfig) -> str | BaseChatModel:
    """Resolve the configured model and optional reasoning effort."""

    return _resolve_model_value(
        model=config.resolved_model(),
        reasoning_effort=config.resolved_reasoning_effort(),
    )


def _resolve_scout_model(config: AgentTeamConfig) -> str | BaseChatModel:
    """Resolve the configured scout model with medium reasoning by default."""

    return _resolve_model_value(
        model=config.resolved_scout_model(),
        reasoning_effort=config.resolved_scout_reasoning_effort(),
    )


def _resolve_model_value(
    *,
    model: str | BaseChatModel,
    reasoning_effort: str | None,
) -> str | BaseChatModel:
    """Resolve a model value and optional reasoning effort."""

    if reasoning_effort is None or not isinstance(model, str):
        return model

    if _is_openai_model(model):
        reasoning: dict[str, str] = {"effort": reasoning_effort}
        if reasoning_effort != "none":
            reasoning["summary"] = "auto"
        model_kwargs: dict[str, Any] = {
            "reasoning": reasoning,
            "use_responses_api": True,
            "output_version": "responses/v1",
        }
    else:
        model_kwargs = {"reasoning_effort": reasoning_effort}

    return init_chat_model(model=model, **model_kwargs)


def _is_openai_model(model: str) -> bool:
    """Return whether a LangChain model string targets OpenAI."""

    if ":" in model:
        provider, _model_name = model.split(":", 1)
        return provider == "openai"

    return model.startswith(("gpt-", "chatgpt-", "o1", "o3", "o4"))


def _existing_memory_files(root_dir: Path, configured: tuple[str, ...]) -> tuple[str, ...]:
    """Return configured/default memory files that exist on disk."""

    candidates = list(configured)
    if not candidates:
        candidates = [
            "AGENTS.md",
            "docs/development-agent-team-architecture.md",
        ]

    existing: list[str] = []
    for candidate in candidates:
        relative = candidate.lstrip("/")
        if (root_dir / relative).exists():
            existing.append("/" + relative)

    return tuple(existing)
