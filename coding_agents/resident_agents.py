"""Resident product and architecture agents."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Sequence

from deepagents import create_deep_agent
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.tools import BaseTool, StructuredTool

from coding_agents.harness import disable_default_general_purpose_subagent
from coding_agents.messages import last_message_text
from coding_agents.permissions import filesystem_permissions
from coding_agents.prompts import PRODUCT_ANALYST_PROMPT, SOFTWARE_ARCHITECT_PROMPT
from coding_agents.safe_filesystem import SafeFilesystemBackend


@dataclass
class ResidentAgentTeam:
    """Long-lived resident agents that keep history through stable thread IDs."""

    product_agent: Any
    architect_agent: Any
    product_thread_id: str
    architect_thread_id: str

    def ask_product_analyst(self, message: str) -> str:
        """Send a message to the resident product analyst."""

        return _invoke_resident(self.product_agent, message, self.product_thread_id)

    def ask_software_architect(self, message: str) -> str:
        """Send a message to the resident software architect."""

        return _invoke_resident(self.architect_agent, message, self.architect_thread_id)

    def manager_tools(self) -> list[BaseTool]:
        """Return manager-only tools for communicating with resident agents."""

        def ask_product_analyst(message: str) -> str:
            """Ask the resident product analyst and continue its prior conversation."""

            return self.ask_product_analyst(message)

        def ask_software_architect(message: str) -> str:
            """Ask the resident software architect and continue its prior conversation."""

            return self.ask_software_architect(message)

        return [
            StructuredTool.from_function(
                func=ask_product_analyst,
                name="ask_product_analyst",
                description=(
                    "Ask the resident product analyst a product, scope, "
                    "requirements, MVP, prioritization, or acceptance-criteria "
                    "question. This resident agent keeps conversation history "
                    "across calls and durable-checkpointer restarts."
                ),
            ),
            StructuredTool.from_function(
                func=ask_software_architect,
                name="ask_software_architect",
                description=(
                    "Ask the resident software architect an architecture, "
                    "technical-design, dependency, risk, or decision-record "
                    "question. This resident agent keeps conversation history "
                    "across calls and durable-checkpointer restarts."
                ),
            ),
        ]


def create_resident_agent_team(
    *,
    model: str | BaseChatModel,
    root_dir: Path,
    artifacts_dir: str,
    parent_thread_id: str,
    tools: Sequence[BaseTool],
    memory: Sequence[str] | None,
    checkpointer: Any,
    debug: bool = False,
) -> ResidentAgentTeam:
    """Create resident product and architecture agents."""

    disable_default_general_purpose_subagent(model)
    backend = SafeFilesystemBackend(root_dir=root_dir, virtual_mode=True)
    permissions = filesystem_permissions("shaping", artifacts_dir, root_dir=root_dir)

    product_agent = create_deep_agent(
        name="product-analyst",
        model=model,
        tools=list(tools),
        system_prompt=_resident_prompt(PRODUCT_ANALYST_PROMPT, artifacts_dir),
        backend=backend,
        permissions=permissions,
        memory=list(memory) if memory else None,
        checkpointer=checkpointer,
        debug=debug,
    )
    architect_agent = create_deep_agent(
        name="software-architect",
        model=model,
        tools=list(tools),
        system_prompt=_resident_prompt(SOFTWARE_ARCHITECT_PROMPT, artifacts_dir),
        backend=backend,
        permissions=permissions,
        memory=list(memory) if memory else None,
        checkpointer=checkpointer,
        debug=debug,
    )

    return ResidentAgentTeam(
        product_agent=product_agent,
        architect_agent=architect_agent,
        product_thread_id=f"{parent_thread_id}:resident:product-analyst",
        architect_thread_id=f"{parent_thread_id}:resident:software-architect",
    )


def _invoke_resident(agent: Any, message: str, thread_id: str) -> str:
    result = agent.invoke(
        {"messages": [{"role": "user", "content": message}]},
        config={"configurable": {"thread_id": thread_id}},
    )
    return last_message_text(result)


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
