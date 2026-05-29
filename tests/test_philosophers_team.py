from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

from coding_agents.teams.philosophers.conversation_counter_tools import (
    create_conversation_counter_tools,
)
from coding_agents.team_instanciator.custom_tool_context import (
    ConversationHistory,
    CustomToolContext,
    EnvView,
)
from coding_agents.team_instanciator.runtime_configuration import RuntimeConfiguration
from coding_agents.team_loader.team_loader import TeamLoader


class PhilosophersTeamTests(unittest.TestCase):
    def test_philosophers_team_loads_with_english_entrypoint_and_counter(self) -> None:
        team = TeamLoader().load("coding_agents/teams/philosophers/team.yaml")

        self.assertEqual(team.id, "philosophers")
        self.assertEqual(team.entrypoint().id if team.entrypoint() else None, "english-philosopher")
        self.assertEqual(
            set(team.agents),
            {"english-philosopher", "german-philosopher", "japanese-philosopher", "translator"},
        )
        self.assertEqual(team.agents["english-philosopher"].toolsets, ("conversation_counter",))
        self.assertEqual(team.custom_tools["english_message_counter"].exposes, ("count_english_messages",))
        self.assertEqual(
            team.custom_tools["english_message_counter"].factory,
            "coding_agents.teams.philosophers.conversation_counter_tools:create_conversation_counter_tools",
        )
        self.assertEqual(len(team.relations), 5)

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
                {
                    "label": "english-philosopher",
                    "limit": 3,
                    "tool_name": "count_english_messages",
                    "outbound_tool_names": ["ask_german_philosopher", "ask_japanese_philosopher"],
                },
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
        self.assertEqual(result["remaining"], 1)
        self.assertIs(result["stop"], False)
        self.assertEqual(result["recommandation"], "continue your conversation")
        self.assertEqual(set(result), {"count", "remaining", "stop", "recommandation"})


if __name__ == "__main__":
    unittest.main()
