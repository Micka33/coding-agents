from __future__ import annotations

import unittest

from src.team_loader.loading.team_loader import TeamLoader


class OpenSpecTeamTests(unittest.TestCase):
    def test_openspec_team_is_studio_conversation_team(self) -> None:
        team = TeamLoader().load("teams/openspec/team.yaml")

        self.assertEqual(team.id, "openspec")
        self.assertEqual(team.defaults.reasoning_effort.default, "xhigh")
        self.assertIsNotNone(team.conversation)
        self.assertEqual(team.conversation.human_input.default_targets, ("openspec-guide",))
        self.assertIsNone(team.conversation.mentions.max_cascade_turns)
        self.assertEqual(
            set(team.agents),
            {
                "openspec-guide",
                "product-strategist",
                "architecture-advisor",
                "change-reviewer",
                "change-writer",
            },
        )
        self.assertEqual(team.entrypoint().id if team.entrypoint() else None, "openspec-guide")
        self.assertEqual(
            {agent_id for agent_id, reference in team.agent_references.items() if reference.conversation is not None},
            {"openspec-guide", "product-strategist", "architecture-advisor", "change-reviewer"},
        )

    def test_guide_prompt_documents_target_project_skill_creation(self) -> None:
        team = TeamLoader().load("teams/openspec/team.yaml")
        prompt = team.agents["openspec-guide"].prompt

        self.assertIn("OpenSpec Studio Developer Experience", prompt)
        self.assertIn("openspec init . --tools codex --force --profile core", prompt)
        self.assertIn("openspec update . --force", prompt)
        self.assertIn(".codex/skills/openspec-explore/SKILL.md", prompt)
        self.assertIn("Run the studio from the target project root", prompt)
        self.assertIn("Always ask `change-reviewer`", prompt)


if __name__ == "__main__":
    unittest.main()
