from __future__ import annotations

from coding_agents.team_loader.agent_definition import AgentDefinition


class AgentRuntimeResolver:
    def subagent_runtime(self, agent: AgentDefinition) -> str:
        if agent.kind == "subagent" and set(agent.toolsets) <= {"scoped_read_tools", "web"}:
            return "langchain"
        return "deepagents_spec"
