"""Factory class for constructing development-agent roles."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from deepagents.backends import BackendProtocol
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.tools import BaseTool

from coding_agents.config import DEFAULT_ARTIFACTS_DIR, AgentMode
from coding_agents.harness import disable_default_general_purpose_subagent
from coding_agents.paths import validate_artifacts_dir
from coding_agents.permissions import filesystem_permissions
from coding_agents.prompts import (
    IMPLEMENTATION_AGENT_DEFINITIONS,
    PRODUCT_ANALYST_PROMPT,
    SOFTWARE_ARCHITECT_PROMPT,
    engineering_manager_prompt,
)
from coding_agents.safe_filesystem import SafeFilesystemBackend
from coding_agents.scout import create_scout_subagent
from coding_agents.vanilla_agent import vanilla_agent


IMPLEMENTATION_AGENT_NAMES = tuple(IMPLEMENTATION_AGENT_DEFINITIONS)
RESIDENT_AGENT_NAMES = ("product-analyst", "software-architect")
AVAILABLE_AGENT_NAMES = (
    "engineering-manager",
    *RESIDENT_AGENT_NAMES,
    "scout",
    *IMPLEMENTATION_AGENT_NAMES,
)

_AGENT_ALIASES = {
    "architect": "software-architect",
    "software-architect": "software-architect",
    "product": "product-analyst",
    "product-analyst": "product-analyst",
    "engineering-manager": "engineering-manager",
    "manager": "engineering-manager",
    "reviewer": "code-reviewer",
    "code-reviewer": "code-reviewer",
    "qa": "qa-engineer",
    "qa-engineer": "qa-engineer",
    "devops": "devops-engineer",
    "devops-engineer": "devops-engineer",
    "security": "security-reviewer",
    "security-reviewer": "security-reviewer",
    "writer": "technical-writer",
    "technical-writer": "technical-writer",
    "developer": "developer",
    "scout": "scout",
}


@dataclass
class AgentFactory:
    """Create standalone agents or subagent specs for any supported role."""

    model: str | BaseChatModel
    root_dir: str | Path = Path(".")
    artifacts_dir: str = DEFAULT_ARTIFACTS_DIR
    tools: Sequence[BaseTool] = field(default_factory=tuple)
    backend: BackendProtocol | None = None
    checkpointer: Any = None
    memory: Sequence[str] | None = None
    debug: bool = False
    mode: AgentMode = "shaping"
    scout_model: str | BaseChatModel | None = None
    implementation_write_paths: Sequence[str] = field(default_factory=tuple)
    skills: Sequence[str] = field(default_factory=tuple)

    def __post_init__(self) -> None:
        self.root_dir = Path(self.root_dir).resolve()
        self.artifacts_dir = validate_artifacts_dir(self.artifacts_dir, self.root_dir)

    def create(
        self,
        agent_name: str,
        *,
        mode: AgentMode | None = None,
        manager_tools: Sequence[BaseTool] = (),
        subagents: Sequence[dict[str, Any]] | None = None,
        auto_transition: bool = False,
    ) -> Any:
        """Create a standalone runnable agent for a supported role."""

        name = normalize_agent_name(agent_name)
        if name == "engineering-manager":
            return self.create_engineering_manager(
                mode=mode,
                manager_tools=manager_tools,
                subagents=subagents or (),
                auto_transition=auto_transition,
            )
        if name == "product-analyst":
            return self.create_resident_agent(name)
        if name == "software-architect":
            return self.create_resident_agent(name)
        if name == "scout":
            return self.create_subagent_spec(name)["runnable"]
        if name in IMPLEMENTATION_AGENT_DEFINITIONS:
            return self.create_implementation_agent(name, mode=mode)
        raise_unknown_agent(name)

    def create_engineering_manager(
        self,
        *,
        mode: AgentMode | None = None,
        manager_tools: Sequence[BaseTool] = (),
        subagents: Sequence[dict[str, Any]] = (),
        auto_transition: bool = False,
    ) -> Any:
        """Create the human-facing engineering-manager Deep Agent."""

        active_mode = mode or self.mode
        return self._create_deep_agent(
            name="engineering-manager",
            system_prompt=engineering_manager_prompt(
                active_mode,
                self.artifacts_dir,
                auto_transition=auto_transition,
            ),
            tools=[*self.tools, *manager_tools],
            mode=active_mode,
            subagents=subagents,
            skills=self.skills,
        )

    def create_resident_agent(self, agent_name: str) -> Any:
        """Create a resident product or architecture Deep Agent."""

        name = normalize_agent_name(agent_name)
        if name == "product-analyst":
            prompt = _resident_prompt(PRODUCT_ANALYST_PROMPT, self.artifacts_dir)
        elif name == "software-architect":
            prompt = _resident_prompt(SOFTWARE_ARCHITECT_PROMPT, self.artifacts_dir)
        else:
            raise_unknown_agent(name)

        return self._create_deep_agent(
            name=name,
            system_prompt=prompt,
            tools=self.tools,
            mode="shaping",
        )

    def create_implementation_agent(
        self,
        agent_name: str,
        *,
        mode: AgentMode | None = None,
    ) -> Any:
        """Create a standalone specialist Deep Agent using the active mode."""

        name = normalize_agent_name(agent_name)
        try:
            _description, system_prompt = IMPLEMENTATION_AGENT_DEFINITIONS[name]
        except KeyError:
            raise_unknown_agent(name)

        return self._create_deep_agent(
            name=name,
            system_prompt=system_prompt,
            tools=self.tools,
            mode=mode or self.mode,
        )

    def create_subagent_spec(self, agent_name: str) -> dict[str, Any]:
        """Create a Deep Agents subagent spec for scout or implementation roles."""

        name = normalize_agent_name(agent_name)
        if name == "scout":
            return create_scout_subagent(
                model=self.scout_model or self.model,
                root_dir=self.root_dir,
                tools=list(self.tools),
            )
        try:
            description, system_prompt = IMPLEMENTATION_AGENT_DEFINITIONS[name]
        except KeyError:
            raise_unknown_agent(name)
        return {
            "name": name,
            "description": description,
            "system_prompt": system_prompt,
            "tools": list(self.tools),
        }

    def create_implementation_subagent_specs(self) -> list[dict[str, Any]]:
        """Create all implementation-mode specialist subagent specs."""

        return [self.create_subagent_spec(name) for name in IMPLEMENTATION_AGENT_NAMES]

    def _create_deep_agent(
        self,
        *,
        name: str,
        system_prompt: str,
        tools: Sequence[BaseTool],
        mode: AgentMode,
        subagents: Sequence[dict[str, Any]] | None = None,
        skills: Sequence[str] | None = None,
    ) -> Any:
        disable_default_general_purpose_subagent(self.model)
        return vanilla_agent(
            agent_type=name,
            model=self.model,
            tools=list(tools),
            system_prompt=system_prompt,
            subagents=list(subagents) if subagents is not None else None,
            skills=(list(skills) or None) if skills is not None else None,
            memory=list(self.memory) if self.memory else None,
            permissions=filesystem_permissions(
                mode,
                self.artifacts_dir,
                self.implementation_write_paths,
                self.root_dir,
            ),
            backend=self._backend(),
            checkpointer=self.checkpointer,
            debug=self.debug,
        ).create()

    def _backend(self) -> BackendProtocol:
        if self.backend is not None:
            return self.backend
        return SafeFilesystemBackend(root_dir=self.root_dir, virtual_mode=True)


def normalize_agent_name(agent_name: str) -> str:
    """Return the canonical name for a supported agent role or alias."""

    normalized = "-".join(agent_name.strip().lower().replace("_", "-").split())
    normalized = "-".join(part for part in normalized.split("-") if part)
    return _AGENT_ALIASES.get(normalized, normalized)


def raise_unknown_agent(agent_name: str) -> None:
    available = ", ".join(AVAILABLE_AGENT_NAMES)
    raise ValueError(f"Unknown agent '{agent_name}'. Available agents: {available}.")


def _resident_prompt(base_prompt: str, artifacts_dir: str) -> str:
    return f"""{base_prompt}

Resident-agent behavior:
- You are a long-lived resident collaborator, not a disposable task subagent.
- Your conversation history with the engineering manager continues across calls
  and can continue across CLI restarts when a durable checkpointer is configured.
- Use that continuity, but keep durable project truth in /{artifacts_dir}.
- If an answer creates or changes project context, update the relevant artifact
  before returning your final response.
"""
