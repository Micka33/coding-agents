from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

from teams.philosophers.conversation_counter_tools import (
    create_conversation_counter_tools,
)
from src.team_instanciator.tools.custom_tool_context import (
    ConversationHistory,
    CustomToolContext,
    EnvView,
)
from src.team_instanciator.configuration.runtime_configuration import RuntimeConfiguration
from src.team_loader.loading.team_loader import TeamLoader


class PhilosophersTeamTests(unittest.TestCase):
    def test_philosophers_team_loads_with_english_entrypoint_and_counter(self) -> None:
        team = TeamLoader().load("teams/philosophers/team.yaml")

        self.assertEqual(team.id, "philosophers")
        self.assertEqual(team.entrypoint().id if team.entrypoint() else None, "Francis-Bacon")
        self.assertEqual(
            set(team.agents),
            {"Francis-Bacon", "Friedrich-Nietzsche", "Hayashi-Razan", "translator"},
        )
        self.assertEqual(team.agents["Francis-Bacon"].toolsets, ("conversation_counter",))
        self.assertEqual(team.custom_tools["english_message_counter"].exposes, ("count_english_messages",))
        self.assertEqual(
            team.custom_tools["english_message_counter"].factory,
            "teams.philosophers.conversation_counter_tools:create_conversation_counter_tools",
        )
        self.assertEqual(len(team.relations), 5)
        self.assertIn(("Hayashi-Razan", "translator"), {(relation.source, relation.target) for relation in team.relations})
        self.assertIn(("Francis-Bacon", "Hayashi-Razan"), {(relation.source, relation.target) for relation in team.relations})

    def test_counter_counts_direct_messages_and_philosopher_tool_messages(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            context = CustomToolContext(
                root_dir=Path(tmp).resolve(),
                env=EnvView(RuntimeConfiguration()),
                runtime_config=RuntimeConfiguration(),
                agent_config=SimpleNamespace(id="english-philosopher"),
                team_config=SimpleNamespace(id="philosophers"),
                history=ConversationHistory(None),
            )
            tool = create_conversation_counter_tools(
                context,
                {},
            )[0]
            runtime = SimpleNamespace(
                config={"configurable": {"thread_id": "thread-1"}},
                state={
                    "messages": [
                        HumanMessage(content="Discuss justice."),
                        AIMessage(content="Let us begin."),
                        AIMessage(
                            content="",
                            tool_calls=[
                                {
                                    "id": "call-1",
                                    "name": "ask_german_philosopher",
                                    "args": {"message": "How do you define justice?"},
                                }
                            ],
                        ),
                        ToolMessage(content="Gerechtigkeit...", tool_call_id="call-1"),
                        AIMessage(
                            content="",
                            tool_calls=[
                                {
                                    "id": "call-2",
                                    "name": "count_english_messages",
                                    "args": {},
                                }
                            ],
                        ),
                    ]
                },
                tool_call_id="call-2",
            )

            result = tool.func(runtime)

        self.assertEqual(result["count"], 2)
        self.assertEqual(result["remaining"], 18)
        self.assertIs(result["stop"], False)
        self.assertEqual(result["recommandation"], "continue your conversation")
        self.assertEqual(set(result), {"count", "remaining", "stop", "recommandation"})


if __name__ == "__main__":
    unittest.main()
