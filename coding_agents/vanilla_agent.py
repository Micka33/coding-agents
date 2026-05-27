"""A minimal, codebase-agnostic Deep Agent factory."""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any, TypeAlias

from deepagents import create_deep_agent
from deepagents.backends import BackendProtocol
from deepagents.middleware.async_subagents import AsyncSubAgent
from deepagents.middleware.filesystem import FilesystemPermission
from deepagents.middleware.subagents import CompiledSubAgent, SubAgent
from langchain.agents.middleware.human_in_the_loop import InterruptOnConfig
from langchain.agents.middleware.types import AgentMiddleware
from langchain.agents.structured_output import AutoStrategy, ProviderStrategy, ToolStrategy
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import SystemMessage
from langchain_core.tools import BaseTool
from langgraph.cache.base import BaseCache
from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.graph.state import CompiledStateGraph
from langgraph.prebuilt.tool_node import ToolRuntime
from langgraph.store.base import BaseStore


# Deep Agents exposes tool dictionaries and response-format dictionaries as
# `dict[str, Any]`; there is no narrower public TypedDict for those shapes.
ToolSpec: TypeAlias = BaseTool | Callable[..., object] | dict[str, Any]
SubAgentSpec: TypeAlias = SubAgent | CompiledSubAgent | AsyncSubAgent
BackendSpec: TypeAlias = BackendProtocol | Callable[[ToolRuntime], BackendProtocol]
ResponseFormatSpec: TypeAlias = (
    ToolStrategy[object]
    | ProviderStrategy[object]
    | AutoStrategy[object]
    | type[object]
    | dict[str, Any]
)


@dataclass
class vanilla_agent:
    """Instantiate a Deep Agent without project-specific role logic."""

    # Agent name passed to Deep Agents as `name`. This can be any role label,
    # for example "engineering-manager", "architect", "developer", or "scout".
    agent_type: str

    # Model identifier or chat model instance accepted by Deep Agents. Typical
    # values are strings like "openai:gpt-5.4", or a provider-specific model
    # object already constructed by the caller.
    model: str | BaseChatModel | None = None

    # Tools exposed to the agent. Deep Agents accepts LangChain BaseTool
    # instances, plain callables, or tool dictionaries depending on the runtime.
    tools: Sequence[ToolSpec] | None = None

    # System instructions for the agent. Usually a string, but Deep Agents also
    # accepts message-like prompt objects, so this remains open-ended.
    system_prompt: str | SystemMessage | None = None

    # Optional LangChain/Deep Agents middleware instances. Use this for generic
    # runtime behavior such as custom hooks or human-in-the-loop middleware.
    middleware: Sequence[AgentMiddleware] = field(default_factory=tuple)

    # Optional subagent definitions. Deep Agents accepts dict specs and compiled
    # subagents; this class passes whatever the caller provides.
    subagents: Sequence[SubAgentSpec] | None = None

    # Skill directory paths used by Deep Agents' skills middleware. Each string
    # usually points to a directory containing skill definitions.
    skills: Sequence[str] | None = None

    # Memory file paths loaded into the agent context by Deep Agents. These are
    # commonly virtual or repository-relative paths, depending on the backend.
    memory: Sequence[str] | None = None

    # Filesystem permission objects understood by Deep Agents. The caller owns
    # their construction; this class does not create or interpret them.
    permissions: Sequence[FilesystemPermission] | None = None

    # Filesystem/runtime backend used by Deep Agents. This can be a backend
    # instance or another backend value accepted by the framework.
    backend: BackendSpec | None = None

    # Human-in-the-loop interrupt configuration keyed by tool name. Values are
    # the booleans or config objects expected by Deep Agents.
    interrupt_on: Mapping[str, bool | InterruptOnConfig] | None = None

    # Optional structured response configuration. This may be a schema, a
    # strategy object, or a provider-specific response format.
    response_format: ResponseFormatSpec | None = None

    # Optional context schema class used to type runtime context passed through
    # the graph.
    context_schema: type[object] | None = None

    # Optional LangGraph checkpointer, `True`, or `None`, exactly as accepted by
    # Deep Agents for persistence.
    checkpointer: BaseCheckpointSaver | bool | None = None

    # Optional LangGraph store used for long-term memory or shared state.
    store: BaseStore | None = None

    # Enables Deep Agents debug mode when true.
    debug: bool = False

    # Optional LangGraph cache object.
    cache: BaseCache | None = None

    # Escape hatch for future Deep Agents keyword arguments. Entries here are
    # merged first, then explicit fields above override matching keys.
    extra_kwargs: Mapping[str, object] = field(default_factory=dict)

    def create(self) -> CompiledStateGraph:
        """Create and return the compiled Deep Agent."""

        return create_deep_agent(**self.kwargs())

    def kwargs(self) -> dict[str, object]:
        """Return the keyword arguments that will be sent to Deep Agents."""

        kwargs: dict[str, object] = dict(self.extra_kwargs)
        kwargs["name"] = self.agent_type
        if self.model is not None:
            kwargs["model"] = self.model
        if self.tools is not None:
            kwargs["tools"] = list(self.tools)
        if self.system_prompt is not None:
            kwargs["system_prompt"] = self.system_prompt
        if self.middleware:
            kwargs["middleware"] = list(self.middleware)
        if self.subagents is not None:
            kwargs["subagents"] = list(self.subagents)
        if self.skills is not None:
            kwargs["skills"] = list(self.skills)
        if self.memory is not None:
            kwargs["memory"] = list(self.memory)
        if self.permissions is not None:
            kwargs["permissions"] = list(self.permissions)
        if self.backend is not None:
            kwargs["backend"] = self.backend
        if self.interrupt_on is not None:
            kwargs["interrupt_on"] = dict(self.interrupt_on)
        if self.response_format is not None:
            kwargs["response_format"] = self.response_format
        if self.context_schema is not None:
            kwargs["context_schema"] = self.context_schema
        if self.checkpointer is not None:
            kwargs["checkpointer"] = self.checkpointer
        if self.store is not None:
            kwargs["store"] = self.store
        if self.debug:
            kwargs["debug"] = self.debug
        if self.cache is not None:
            kwargs["cache"] = self.cache
        return kwargs

    def __call__(self) -> CompiledStateGraph:
        """Create the agent when the wrapper is called directly."""

        return self.create()


VanillaAgent = vanilla_agent

__all__ = ["VanillaAgent", "vanilla_agent"]
