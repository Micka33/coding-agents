from __future__ import annotations

import unittest
from pathlib import Path
from unittest.mock import patch

from coding_agents.vanilla_agent import VanillaAgent, vanilla_agent


class VanillaAgentTests(unittest.TestCase):
    def test_vanilla_agent_passes_generic_deep_agent_arguments(self) -> None:
        with patch("coding_agents.vanilla_agent.create_deep_agent", return_value="compiled") as create:
            agent = vanilla_agent(
                agent_type="architect",
                model="test:model",
                tools=["tool"],
                system_prompt="You are an architect.",
                subagents=[{"name": "scout"}],
                skills=["skills/custom"],
                memory=["/AGENTS.md"],
                permissions=["permission"],
                backend="backend",
                interrupt_on={"write_file": True},
                checkpointer="checkpointer",
                store="store",
                debug=True,
                cache="cache",
                extra_kwargs={"response_format": "format"},
            ).create()

        self.assertEqual(agent, "compiled")
        create.assert_called_once_with(
            name="architect",
            model="test:model",
            tools=["tool"],
            system_prompt="You are an architect.",
            subagents=[{"name": "scout"}],
            skills=["skills/custom"],
            memory=["/AGENTS.md"],
            permissions=["permission"],
            backend="backend",
            interrupt_on={"write_file": True},
            response_format="format",
            checkpointer="checkpointer",
            store="store",
            debug=True,
            cache="cache",
        )

    def test_pascal_case_alias_uses_same_class(self) -> None:
        self.assertIs(VanillaAgent, vanilla_agent)

    def test_module_has_no_project_specific_imports(self) -> None:
        source = Path("coding_agents/vanilla_agent.py").read_text(encoding="utf-8")

        self.assertNotIn("coding_agents.", source)
        self.assertNotIn("AgentTeamConfig", source)
        self.assertNotIn("filesystem_permissions", source)


if __name__ == "__main__":
    unittest.main()
