from __future__ import annotations

import sqlite3
import tempfile
import threading
import unittest
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from langgraph.types import Overwrite

from src.team_instanciator.conversation.agent_delivery_state import AgentDeliveryState
from src.team_instanciator.runtime.checkpointer_handle import CheckpointerHandle
from src.team_instanciator.factories.checkpoint_metadata_factory import CheckpointMetadataFactory
from src.team_instanciator.conversation import (
    AgentSyncBuilder,
    ConversationDeliveryError,
    ConversationDelivery,
    ConversationEvent,
    ConversationFileRef,
    ConversationInterrupt,
    ConversationRuntimeState,
    ConversationRuntimeController,
    ConversationStore,
    MentionAwareTeam,
    MentionParser,
    PublicReplyExtractor,
)
from src.team_instanciator.conversation.dispatch_context import DispatchContext
from src.team_instanciator.runtime.thread_id_factory import ThreadIdFactory
from src.team_loader.models.conversation_settings import AgentConversationSettings, TeamConversationSettings
from tests.support import agent, team


def conversation_reference(*aliases: str) -> SimpleNamespace:
    return SimpleNamespace(
        kind="deepagent",
        config="agent.mdc",
        conversation=AgentConversationSettings(aliases=tuple(aliases)),
    )


class FakeGraph:
    def __init__(self, response: str, callback=None) -> None:
        self.response = response
        self.callback = callback
        self.calls: list[tuple[Any, Any]] = []
        self.updates: list[tuple[Any, Any]] = []
        self.interrupted = False

    def invoke(self, input: Any, config: Any = None):
        self.calls.append((input, config))
        if self.callback is not None:
            self.callback(self, input, config)
        return {"messages": [AIMessage(content=self.response, id=f"msg-{len(self.calls)}")]}

    def update_state(self, config: Any, values: Any):
        self.updates.append((config, values))
        updated = dict(config)
        updated["configurable"] = {
            **dict(config.get("configurable", {})),
            "checkpoint_id": f"fork-{len(self.updates)}",
        }
        return updated

    def interrupt(self):
        self.interrupted = True


class RaisingInterruptGraph(FakeGraph):
    def interrupt(self):
        super().interrupt()
        raise RuntimeError("cannot interrupt")


class FakeRegistry:
    def __init__(self, graphs: dict[str, FakeGraph]) -> None:
        self.graphs = graphs

    def graph(self, agent_id: str) -> FakeGraph:
        return self.graphs[agent_id]


class ConversationRuntimeTests(unittest.TestCase):
    def test_parser_resolves_aliases_and_ignores_code_unknown_nonparticipants_and_self_mentions(self) -> None:
        parser = MentionParser({"agent-a", "agent-b"}, {"architect": "agent-b"})

        mentions = parser.parse(
            "Ask @agent-a and @architect, not @missing, `@agent-b`, or:\n```text\n@agent-b\n```",
            author_id="agent-a",
        )

        self.assertEqual(mentions, ("agent-b",))

    def test_parser_builds_alias_lookup_from_team(self) -> None:
        team_config = team(
            agents={"agent-a": agent("agent-a", entrypoint=True), "agent-b": agent("agent-b")},
            agent_references={
                "agent-a": conversation_reference("lead"),
                "agent-b": conversation_reference("architect"),
            },
        )

        parser = MentionParser.from_team(team_config)

        self.assertEqual(parser.parse("@architect and @lead"), ("agent-b", "agent-a"))

    def test_runtime_records_convert_to_dicts(self) -> None:
        file_ref = ConversationFileRef(id="file", filename="notes.txt", uri="conversation://files/file")
        event = ConversationEvent(
            id="event",
            team_id="team",
            conversation_id="thread",
            seq=1,
            created_at="now",
            author_id="human",
            author_kind="human",
            content="hello",
            mentions=("agent",),
            attachments=(file_ref,),
            metadata={"kind": "test"},
        )
        state = AgentDeliveryState(team_id="team", conversation_id="thread", agent_id="agent")
        runtime_state = ConversationRuntimeState(team_id="team", conversation_id="thread")
        delivery = ConversationDelivery(
            id="delivery",
            team_id="team",
            conversation_id="thread",
            agent_id="agent",
            run_id="run",
            snapshot_seq=1,
            status="failed",
            created_at="now",
            error="boom",
        )
        interrupt = ConversationInterrupt(
            id="interrupt",
            team_id="team",
            conversation_id="thread",
            created_at="now",
            kind="approve",
            payload={"action": "write_file"},
        )

        self.assertEqual(event.to_dict()["attachments"][0]["filename"], "notes.txt")
        self.assertEqual(state.to_dict()["agent_id"], "agent")
        self.assertTrue(runtime_state.to_dict()["mention_hook_enabled"])
        self.assertEqual(delivery.to_dict()["error"], "boom")
        self.assertEqual(interrupt.to_dict()["payload"]["action"], "write_file")
        result = SimpleNamespace(deliveries=(delivery,))
        self.assertEqual(
            tuple(item.status for item in __import__(
                "src.team_instanciator.conversation.conversation_append_result",
                fromlist=["ConversationAppendResult"],
            ).ConversationAppendResult(event=event, deliveries=result.deliveries).failures),
            ("failed",),
        )

    def test_store_persists_events_files_runtime_state_and_delivery_state_in_sqlite(self) -> None:
        with sqlite3.connect(":memory:", check_same_thread=False) as connection:
            connection.execute(
                """
                create table team_conversation_branches (
                    team_id text not null,
                    conversation_id text not null,
                    id text not null,
                    label text not null,
                    parent_branch_id text,
                    origin_checkpoint_id text,
                    created_at text not null,
                    current integer not null,
                    head_checkpoint_id text,
                    primary key (team_id, conversation_id, id)
                )
                """
            )
            store = ConversationStore(team_id="team", conversation_id="thread", connection=connection)
            file_ref = ConversationFileRef(id="file-1", filename="notes.txt", uri="conversation://files/file-1")

            event = store.append_event(
                author_id="human",
                author_kind="human",
                content="@agent please",
                mentions=("agent",),
                attachments=(file_ref,),
            )
            store.enqueue("agent", event.seq)
            store.update_runtime_state(mention_hook_enabled=False, max_cascade_turns=3)
            store.record_delivery(agent_id="agent", status="failed", error="boom")
            branch = store.create_branch(
                label="Alternative",
                origin_checkpoint_id="checkpoint_01",
                head_checkpoint_id="checkpoint_01",
            )
            interrupt = store.create_interrupt(
                kind="approve",
                payload={"action": "write_file"},
                run_id="run_01",
                agent_id="agent",
                checkpoint_id="checkpoint_01",
            )
            resolved = store.resume_interrupt(interrupt.id, decision="approve", response="ok")
            store.switch_branch(branch.id)

            reloaded = ConversationStore(team_id="team", conversation_id="thread", connection=connection)

            self.assertEqual(reloaded.list_events()[0].attachments[0].filename, "notes.txt")
            self.assertEqual(reloaded.list_events(through_seq=event.seq)[0].id, event.id)
            self.assertEqual(reloaded.get_runtime_state().mention_hook_enabled, False)
            self.assertEqual(reloaded.get_runtime_state().max_cascade_turns, 3)
            self.assertEqual(reloaded.ensure_agent_state("agent").queued_after_seq, event.seq)
            self.assertEqual(reloaded.list_deliveries()[0].error, "boom")
            self.assertEqual(reloaded.list_branches()[0].label, "Alternative")
            self.assertEqual(resolved.status if resolved else None, "resolved")
            self.assertEqual(reloaded.list_interrupts(), [])
            self.assertEqual(reloaded.list_interrupts(active_only=False)[0].decisions[0]["response"], "ok")
            self.assertEqual(reloaded.current_branch_id(), branch.id)
            self.assertIsNone(reloaded.switch_branch("missing"))
            self.assertIsNone(reloaded.switch_branch("branch_main"))
            self.assertEqual(reloaded.current_branch_id(), "branch_main")
            self.assertIn(
                "origin_event_id",
                [row[1] for row in connection.execute("pragma table_info(team_conversation_branches)").fetchall()],
            )

    def test_store_cancels_and_clears_pending_queue_without_stopping_running_agents(self) -> None:
        store = ConversationStore(team_id="team", conversation_id="thread")
        event = store.append_event(author_id="human", author_kind="human", content="@agent")
        pending = store.enqueue("agent", event.seq)
        running = store.enqueue("running-agent", event.seq)

        store.save_agent_state(replace(running, running=True))

        cancelled = store.cancel_queued("agent")
        still_running = store.cancel_queued("running-agent")
        store.enqueue("agent", event.seq)
        cleared = store.clear_pending_queue()

        self.assertFalse(cancelled.queued)
        self.assertTrue(still_running.running)
        self.assertTrue(still_running.queued)
        self.assertEqual([state.agent_id for state in cleared], ["agent"])
        self.assertFalse(store.ensure_agent_state("agent").queued)
        self.assertTrue(store.ensure_agent_state("running-agent").queued)
        self.assertEqual(pending.queued_after_seq, event.seq)

    def test_store_tracks_in_memory_branch_metadata(self) -> None:
        store = ConversationStore(team_id="team", conversation_id="thread")

        branch = store.create_branch(origin_checkpoint_id="checkpoint_01", head_checkpoint_id="checkpoint_01")
        missing = store.switch_branch("missing")
        selected = store.switch_branch(branch.id)

        self.assertEqual(branch.label, "Branch 1")
        self.assertEqual(branch.to_dict()["head_checkpoint_id"], "checkpoint_01")
        self.assertIsNone(missing)
        self.assertEqual(selected.id if selected else None, branch.id)
        self.assertEqual(store.current_branch_id(), branch.id)
        self.assertTrue(store.list_branches()[0].current)
        self.assertIsNone(store.switch_branch("branch_main"))
        self.assertEqual(store.current_branch_id(), "branch_main")
        self.assertFalse(store.list_branches()[0].current)

    def test_store_tracks_in_memory_interrupts_and_validation_edges(self) -> None:
        store = ConversationStore(team_id="team", conversation_id="thread")

        interrupt = store.create_interrupt(
            kind="review",
            payload={"draft": "hello"},
            run_id="run_01",
            agent_id="agent",
            checkpoint_id="checkpoint_01",
        )
        resolved = store.resume_interrupt(
            interrupt.id,
            decision="edit",
            response="updated",
            edited_payload={"draft": "updated"},
        )

        self.assertEqual(store.list_interrupts(), [])
        self.assertEqual(store.list_interrupts(active_only=False)[0].kind, "review")
        self.assertEqual(resolved.decisions[0]["edited_payload"], {"draft": "updated"} if resolved else None)
        self.assertIsNone(store.resume_interrupt("missing", decision="approve"))
        with self.assertRaisesRegex(ValueError, "kind"):
            store.create_interrupt(kind="bad", payload={})  # type: ignore[arg-type]
        with self.assertRaisesRegex(ValueError, "decision"):
            store.resume_interrupt(interrupt.id, decision="bad")  # type: ignore[arg-type]
        with self.assertRaisesRegex(ValueError, "payload"):
            store.create_interrupt(kind="approve", payload={"bad": object()})  # type: ignore[arg-type]
        with self.assertRaisesRegex(ValueError, "edited_payload"):
            store.resume_interrupt(interrupt.id, decision="approve", edited_payload={"bad": object()})  # type: ignore[arg-type]

    def test_runtime_controller_cancels_and_clears_pending_queue(self) -> None:
        store = ConversationStore(team_id="team", conversation_id="thread")
        event = store.append_event(author_id="human", author_kind="human", content="@agent")
        store.enqueue("agent", event.seq)
        controller = ConversationRuntimeController(SimpleNamespace(store=store, router=SimpleNamespace(stop=lambda _agent_id: None)))

        self.assertEqual(controller.cancel_queued_agent("agent")["team_id"], "team")
        self.assertFalse(store.ensure_agent_state("agent").queued)

        store.enqueue("agent", event.seq)
        controller.clear_queue("failed")
        self.assertTrue(store.ensure_agent_state("agent").queued)

        controller.clear_queue("all")
        self.assertFalse(store.ensure_agent_state("agent").queued)

        branch = controller.create_branch(label="Alternative", origin_checkpoint_id="checkpoint_01")
        controller.switch_branch(branch.id)
        self.assertEqual(controller.list_branches()[0].id, branch.id)
        self.assertEqual(controller.current_branch_id(), branch.id)
        self.assertIsNone(controller.switch_branch("missing"))

        interrupt = controller.create_interrupt(kind="approve", payload={"action": "send"}, agent_id="agent")
        self.assertEqual(controller.list_interrupts()[0].id, interrupt.id)
        self.assertEqual(controller.resume_interrupt(interrupt.id, decision="approve").status, "resolved")

    def test_checkpoint_resume_replays_graph_into_branch_scoped_event(self) -> None:
        graph = FakeGraph("resumed")
        runtime = self._conversation_runtime({"agent-b": graph})
        origin = runtime.store.append_event(
            author_id="human",
            author_kind="human",
            content="@agent-b original",
            mentions=("agent-b",),
        )

        result = runtime.resume_checkpoint(
            checkpoint_id="checkpoint_01",
            checkpoint_ns="",
            thread_id="thread:mention:agent-b",
            mode="resume",
            origin_event_id=origin.id,
            origin_event_seq=origin.seq,
        )

        self.assertEqual(graph.calls[0][0], None)
        self.assertEqual(graph.calls[0][1]["configurable"]["checkpoint_id"], "checkpoint_01")
        self.assertEqual(result.event.metadata["branch_id"], result.branch.id)
        self.assertEqual(result.branch.origin_event_id, origin.id)
        self.assertEqual(runtime.store.current_branch_id(), result.branch.id)

    def test_checkpoint_edit_updates_graph_state_before_replay(self) -> None:
        graph = FakeGraph("edited")
        runtime = self._conversation_runtime({"agent-b": graph})

        result = runtime.runtime.resume_checkpoint(
            checkpoint_id="checkpoint_01",
            checkpoint_ns="",
            thread_id="thread:mention:agent-b",
            mode="edit",
            edited_content="replacement",
        )

        self.assertEqual(graph.updates[0][1]["messages"][0].content, "replacement")
        self.assertEqual(graph.calls[0][1]["configurable"]["checkpoint_id"], "fork-1")
        self.assertEqual(result.mode, "edit")

        with self.assertRaisesRegex(ValueError, "edited_content"):
            runtime.runtime.resume_checkpoint(
                checkpoint_id="checkpoint_01",
                checkpoint_ns="",
                thread_id="thread:mention:agent-b",
                mode="edit",
            )
        with self.assertRaisesRegex(ValueError, "mention thread"):
            runtime.resume_checkpoint(checkpoint_id="checkpoint_01", checkpoint_ns="", thread_id="thread")

        no_update = SimpleNamespace(invoke=lambda _input, config=None: {"messages": [AIMessage(content="ok")]})
        runtime.registry.graphs["agent-b"] = no_update
        with self.assertRaisesRegex(ValueError, "update_state"):
            runtime.resume_checkpoint(
                checkpoint_id="checkpoint_01",
                checkpoint_ns="",
                thread_id="thread:mention:agent-b",
                mode="edit",
                edited_content="replacement",
            )

        runtime.registry.graphs["agent-b"] = FakeGraph("")
        with self.assertRaisesRegex(ValueError, "no final textual"):
            runtime.resume_checkpoint(checkpoint_id="checkpoint_01", checkpoint_ns="", thread_id="thread:mention:agent-b")

        runtime.registry.graphs["agent-b"] = FakeGraph("regenerated")
        regenerated = runtime.resume_checkpoint(
            checkpoint_id="checkpoint_01",
            checkpoint_ns="",
            thread_id="thread:mention:agent-b",
            mode="regenerate",
        )
        self.assertEqual(regenerated.branch.label, "Checkpoint regenerate")

    def test_store_private_helpers_are_noops_without_sqlite_connection(self) -> None:
        store = ConversationStore(team_id="team", conversation_id="thread")
        file_ref = ConversationFileRef(id="file-1", filename="notes.txt", uri="conversation://files/file-1")
        event = store.append_event(
            author_id="human",
            author_kind="human",
            content="hello",
            attachments=(file_ref,),
        )

        store._initialize_sqlite()
        store._upsert_runtime_state(store.get_runtime_state())
        store._ensure_column("team_conversation_branches", "origin_event_id", "text")

        self.assertEqual(store._attachments_for(event.id), [file_ref])
        self.assertEqual(store._attachments_for("missing"), [])

    def test_sync_builder_projects_other_participants_as_human_messages_with_attachments_and_identity(self) -> None:
        store = ConversationStore(team_id="team", conversation_id="thread")
        event = store.append_event(
            author_id="human",
            author_kind="human",
            content="@agent-b hello",
            mentions=("agent-b",),
            attachments=(ConversationFileRef(id="file-1", filename="notes.txt", uri="conversation://files/file-1"),),
        )
        state = store.ensure_agent_state("agent-b")
        target = agent("agent-b", description="Reviews implementation details.")

        sync = AgentSyncBuilder(identity_refresh_after_tokens=10_000).build(
            target=target,
            state=state,
            events=[event],
        )

        self.assertEqual(sync.snapshot_seq, 1)
        self.assertEqual(sync.messages[0].type, "system")
        self.assertEqual(
            sync.messages[0].content,
            "\n".join(
                [
                    "You are agent-b. Other participants refer to you as @agent-b.",
                    "Other participants are:",
                    "- None.",
                    "You can mention other participants by writing @<participant_id> or @<participant_alias>",
                    "If you answer to another participant, mention them in your reply.",
                    "If you need ask a question to another participant, mention them in your reply.",
                ]
            ),
        )
        self.assertEqual(sync.messages[1].type, "human")
        self.assertEqual(sync.messages[1].name, "human")
        self.assertEqual(sync.messages[1].additional_kwargs["attachments"][0]["filename"], "notes.txt")
        self.assertEqual(
            sync.messages[1].additional_kwargs["attachments"][0]["read_path"],
            "/.coding-agents/conversations/thread/files/file-1",
        )

    def test_sync_builder_identity_lists_other_participants_with_aliases_and_descriptions(self) -> None:
        state = ConversationStore(team_id="team", conversation_id="thread").ensure_agent_state("agent-b")
        target = agent("agent-b", description="Reviews implementation details.")

        sync = AgentSyncBuilder(
            participants=(
                agent("agent-a", description="Coordinates the conversation."),
                target,
                agent("agent-c", description="Checks quality risks."),
                agent("agent-d", description="Handles releases."),
            ),
            aliases_by_participant={
                "agent-a": ("lead", "agent_a"),
                "agent-c": ("qa",),
            },
        ).build(
            target=target,
            state=state,
            events=[
                ConversationEvent(
                    id="event",
                    team_id="team",
                    conversation_id="thread",
                    seq=1,
                    created_at="now",
                    author_id="human",
                    author_kind="human",
                    content="@agent-b hello",
                    mentions=("agent-b",),
                )
            ],
        )

        self.assertEqual(
            sync.messages[0].content,
            "\n".join(
                [
                    "You are agent-b. Other participants refer to you as @agent-b.",
                    "Other participants are:",
                    "- agent-a (aliases: lead, agent_a) : Coordinates the conversation.",
                    "- agent-c (aliases: qa) : Checks quality risks.",
                    "- agent-d : Handles releases.",
                    "You can mention other participants by writing @<participant_id> or @<participant_alias>",
                    "If you answer to another participant, mention them in your reply.",
                    "If you need ask a question to another participant, mention them in your reply.",
                ]
            ),
        )

    def test_sync_builder_handles_empty_delta_and_token_limit(self) -> None:
        state = ConversationStore(team_id="team", conversation_id="thread").ensure_agent_state("agent-b")
        empty_sync = AgentSyncBuilder().build(target=agent("agent-b"), state=state, events=[])

        self.assertEqual(empty_sync.projected_event_count, 0)
        with self.assertRaisesRegex(ConversationDeliveryError, "above the configured limit"):
            AgentSyncBuilder(max_delta_tokens=1).build(
                target=agent("agent-b"),
                state=state,
                events=[
                    ConversationEvent(
                        id="event",
                        team_id="team",
                        conversation_id="thread",
                        seq=1,
                        created_at="now",
                        author_id="human",
                        author_kind="human",
                        content="this is definitely too long",
                        mentions=("agent-b",),
                    )
                ],
            )

    def test_reply_extractor_uses_last_textual_ai_message_only(self) -> None:
        reply = PublicReplyExtractor().extract(
            {
                "messages": [
                    AIMessage(content="", tool_calls=[{"id": "call", "name": "tool", "args": {}}]),
                    ToolMessage(content="tool result", tool_call_id="call"),
                    AIMessage(content="final", id="final-id"),
                ]
            }
        )

        self.assertEqual(reply.content if reply else None, "final")
        self.assertEqual(reply.source_message_id if reply else None, "final-id")

    def test_reply_extractor_handles_missing_messages_objects_lists_and_non_text(self) -> None:
        extractor = PublicReplyExtractor()

        self.assertIsNone(extractor.extract({}))
        self.assertIsNone(extractor.extract({"messages": [SimpleNamespace(type="tool", content="ignored")]}))
        self.assertIsNone(extractor.extract({"messages": [SimpleNamespace(type="ai", content=None)]}))
        reply = extractor.extract(
            {
                "messages": [
                    SimpleNamespace(
                        role="assistant",
                        id=42,
                        content=[
                            {"type": "image", "url": "ignored"},
                            {"type": "text", "content": "hello"},
                            "world",
                        ],
                    )
                ]
            }
        )

        self.assertEqual(reply.content if reply else None, "hello\nworld")
        self.assertEqual(reply.source_message_id if reply else None, "42")
        numeric_reply = extractor.extract({"messages": [{"role": "assistant", "content": 123}]})
        self.assertEqual(numeric_reply.content if numeric_reply else None, "123")

    def test_mention_aware_team_appends_human_message_runs_agent_and_appends_public_reply(self) -> None:
        graph = FakeGraph("I agree. @agent-c should weigh in.")
        graph_c = FakeGraph("Looks good.")
        runtime = self._conversation_runtime({"agent-b": graph, "agent-c": graph_c})

        result = runtime.append_human_message("@agent-b please review", author_id="mickael")

        events = runtime.store.list_events()
        self.assertEqual(result.event.mentions, ("agent-b",))
        self.assertEqual([event.author_id for event in events], ["mickael", "agent-b", "agent-c"])
        self.assertEqual(graph.calls[0][0]["messages"][1].name, "mickael")
        self.assertIn(":mention:agent-b", graph.calls[0][1]["configurable"]["thread_id"])

    def test_mention_aware_team_identity_uses_team_aliases_and_agent_descriptions(self) -> None:
        graph = FakeGraph("answer")
        team_config = team(
            team_id="team",
            agents={
                "agent-a": agent("agent-a", entrypoint=True, description="Coordinates the conversation."),
                "agent-b": agent("agent-b", description="Reviews implementation details."),
            },
            agent_references={
                "agent-a": conversation_reference("lead"),
                "agent-b": conversation_reference("reviewer"),
            },
            conversation=TeamConversationSettings.from_mapping({}),
        )
        runtime = MentionAwareTeam(
            team=team_config,
            registry=FakeRegistry({"agent-b": graph}),
            checkpointer_handle=CheckpointerHandle("checkpointer"),
            root_dir=Path.cwd(),
            conversation_id="thread",
            thread_id_factory=ThreadIdFactory(),
            checkpoint_metadata_factory=CheckpointMetadataFactory(),
        )

        runtime.append_human_message("@reviewer please", author_id="mickael")

        self.assertEqual(
            runtime.state()["participant_aliases"],
            {"agent-a": ["lead"], "agent-b": ["reviewer"]},
        )
        self.assertIn(
            "- agent-a (aliases: lead) : Coordinates the conversation.",
            graph.calls[0][0]["messages"][0].content,
        )

    def test_disabled_hook_records_mentions_without_delivery_and_reenabled_does_not_backfill(self) -> None:
        graph = FakeGraph("answer")
        runtime = self._conversation_runtime({"agent-b": graph})
        runtime.runtime.set_mention_hook_enabled(False)
        runtime.runtime.set_max_cascade_turns(2)
        runtime.runtime.set_max_cascade_turns(None)
        with self.assertRaisesRegex(ValueError, "max_cascade_turns"):
            runtime.runtime.set_max_cascade_turns(0)

        runtime.append_human_message("@agent-b later", author_id="mickael")
        runtime.runtime.set_mention_hook_enabled(True)
        runtime.append_human_message("plain note", author_id="mickael")

        self.assertEqual(runtime.store.list_events()[0].mentions, ("agent-b",))
        self.assertEqual(graph.calls, [])

    def test_attachment_file_is_copied_and_delivered_to_private_thread(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "notes.txt"
            source.write_text("hello", encoding="utf-8")
            graph = FakeGraph("answer")
            runtime = self._conversation_runtime({"agent-b": graph}, root=root)

            runtime.append_human_message("@agent-b see file", files=[source])

            attachment = graph.calls[0][0]["messages"][1].additional_kwargs["attachments"][0]
            self.assertEqual(attachment["filename"], "notes.txt")
            self.assertTrue((root / ".coding-agents" / "conversations" / "thread" / "files" / attachment["id"]).is_file())

    def test_mentions_while_running_collapse_into_one_follow_up_without_skipping_cursor(self) -> None:
        runtime_holder = {}

        def callback(graph, _input, _config):
            if len(graph.calls) == 1:
                runtime_holder["runtime"].append_human_message("@agent-b second", author_id="mickael", wait=False)
                runtime_holder["runtime"].append_human_message("@agent-b third", author_id="mickael", wait=False)

        graph = FakeGraph("first answer", callback=callback)
        runtime = self._conversation_runtime({"agent-b": graph})
        runtime_holder["runtime"] = runtime

        runtime.append_human_message("@agent-b first", author_id="mickael")

        self.assertEqual(len(graph.calls), 2)
        second_call_messages = graph.calls[1][0]["messages"]
        self.assertEqual([message.content for message in second_call_messages if message.type == "human"], ["@agent-b second", "@agent-b third"])
        self.assertEqual(runtime.store.ensure_agent_state("agent-b").last_delivered_seq, 4)

    def test_state_reports_all_running_and_queued_activities(self) -> None:
        runtime = self._conversation_runtime({"agent-b": FakeGraph("answer"), "agent-c": FakeGraph("answer")})
        state_b = runtime.store.ensure_agent_state("agent-b")
        state_c = runtime.store.ensure_agent_state("agent-c")
        runtime.store.save_agent_state(
            replace(state_b, running=True, current_run_id="run-b", current_snapshot_seq=1)
        )
        runtime.store.save_agent_state(replace(state_c, queued=True, queued_after_seq=1))

        state = runtime.state()

        self.assertEqual([item["agent_id"] for item in state["activities"]], ["agent-b", "agent-c"])
        self.assertEqual(state["activity"]["agent_id"] if state["activity"] else None, "agent-b")

    def test_stopped_run_ignores_late_reply_and_queued_follow_up_runs(self) -> None:
        runtime_holder = {}

        def callback(graph, _input, _config):
            if len(graph.calls) == 1:
                runtime_holder["runtime"].runtime.stop_agent("agent-b")
                runtime_holder["runtime"].append_human_message("@agent-b latest", author_id="mickael", wait=False)

        graph = FakeGraph("late answer", callback=callback)
        runtime = self._conversation_runtime({"agent-b": graph})
        runtime_holder["runtime"] = runtime

        runtime.append_human_message("@agent-b first", author_id="mickael")

        self.assertTrue(graph.interrupted)
        self.assertEqual(len(graph.calls), 2)
        self.assertEqual([event.author_id for event in runtime.store.list_events()], ["mickael", "mickael", "agent-b"])
        self.assertEqual([delivery.status for delivery in runtime.store.list_deliveries()], ["stopped", "success"])

    def test_router_covers_empty_skipped_failed_empty_ignored_and_cascade_limited_runs(self) -> None:
        runtime = self._conversation_runtime(
            {
                "agent-b": FakeGraph("answer"),
                "agent-c": FakeGraph(""),
                "agent-d": FakeGraph("answer", callback=lambda *_args: (_ for _ in ()).throw(RuntimeError("boom"))),
                "agent-e": FakeGraph("ignored"),
                "agent-f": FakeGraph("@agent-b cascade"),
            }
        )

        runtime.router._run_agent("agent-b", DispatchContext())
        self.assertEqual(runtime.store.list_deliveries(), [])

        own_event = runtime.store.append_event(
            author_id="agent-b",
            author_kind="agent",
            content="self-authored",
            mentions=("agent-b",),
        )
        runtime.router.enqueue_targets(own_event, ("agent-b",))
        runtime.router.drain()
        self.assertEqual(runtime.store.list_deliveries()[-1].status, "skipped")

        runtime.append_human_message("@agent-c empty", wait=True)
        runtime.append_human_message("@agent-d fail", wait=True)

        def rewrite_run_id(_graph, _input, _config):
            state = runtime.store.ensure_agent_state("agent-e")
            runtime.store.save_agent_state(replace(state, current_run_id="different-run"))

        runtime.registry.graphs["agent-e"].callback = rewrite_run_id
        runtime.append_human_message("@agent-e ignored", wait=True)

        runtime.store.update_runtime_state(max_cascade_turns=0)
        runtime.append_human_message("@agent-f cascade", wait=True)

        self.assertIn("empty", [delivery.status for delivery in runtime.store.list_deliveries()])
        self.assertIn("failed", [delivery.status for delivery in runtime.store.list_deliveries()])
        self.assertIn("ignored", [delivery.status for delivery in runtime.store.list_deliveries()])
        self.assertIn("cascade-limited", [delivery.status for delivery in runtime.store.list_deliveries()])

    def test_router_dispatch_stop_wait_and_disabled_cascade_edges(self) -> None:
        blocked = threading.Event()
        alive = threading.Thread(target=blocked.wait)
        graph = RaisingInterruptGraph("@agent-c follow")
        runtime = self._conversation_runtime({"agent-b": graph, "agent-c": FakeGraph("answer")})

        runtime.router.drain()
        object.__setattr__(runtime.team.conversation, "mentions", SimpleNamespace(max_parallel_agents=0))
        event = runtime.store.append_event(author_id="human", author_kind="human", content="@agent-b", mentions=("agent-b",))
        runtime.router.enqueue_targets(event, ("agent-b",))
        runtime.router.drain()
        self.assertEqual(graph.calls, [])

        alive.start()
        runtime.router._background_thread = alive
        runtime.router.dispatch(wait=False)
        blocked.set()
        runtime.router.wait_for_idle()
        alive.join()

        runtime.store.save_agent_state(
            replace(runtime.store.ensure_agent_state("agent-b"), running=True, current_run_id="run")
        )
        runtime.router.stop("agent-b")
        self.assertTrue(graph.interrupted)

        runtime.store.update_runtime_state(mention_hook_enabled=False)
        runtime.router._append_public_reply(
            "agent-b",
            "@agent-c disabled",
            source_thread_id="thread:mention:agent-b",
            source_message_id=None,
            context=DispatchContext(),
        )
        self.assertFalse(runtime.store.ensure_agent_state("agent-c").queued)

    def test_mention_aware_team_state_activity_files_private_messages_and_agent_messages(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            connection = sqlite3.connect(":memory:", check_same_thread=False)
            runtime = self._conversation_runtime({"agent-b": FakeGraph("answer")}, root=root, connection=connection)
            memory_runtime = self._conversation_runtime({"agent-b": FakeGraph("answer")}, root=root)

            same = runtime.with_conversation_id("thread")
            other = runtime.with_conversation_id("other-thread")
            self.assertIs(same, runtime)
            self.assertEqual(other.conversation_id, "other-thread")
            self.assertEqual(memory_runtime.activity("agent-b")["private_messages"], [])
            self.assertEqual(runtime.activity("agent-b")["private_messages"], [])

            dict_ref_event = runtime.append_human_message(
                "@agent-b dict",
                files=[{"id": "dict-file", "filename": "dict.txt", "uri": "conversation://files/dict-file"}],
            ).event
            existing_ref = ConversationFileRef(id="existing", filename="existing.txt", uri="conversation://files/existing")
            runtime.append_human_message("@agent-b existing", files=[existing_ref])
            public_ref = runtime.create_public_file_ref(filename="upload.txt", content=b"hello", added_by="human")
            runtime.append_agent_message(agent_id="agent-b", content="@agent-b self ignored")
            runtime.append_agent_message(agent_id="agent-b", content="@agent-b no hook")
            dispatch_calls = []
            runtime.router.dispatch = lambda wait=False: dispatch_calls.append(wait)
            runtime.append_agent_message(agent_id="agent-b", content="@agent-b asks @agent-b and @agent-b")
            runtime.append_agent_message(agent_id="agent-b", content="@agent-a hello")
            runtime.wait_for_idle()

            self.assertEqual(dict_ref_event.attachments[0].id, "dict-file")
            self.assertEqual(public_ref.size_bytes, 5)
            self.assertIn("agent-b", runtime.state()["participants"])
            self.assertEqual(runtime.activity()["conversation_id"], "thread")
            self.assertEqual(dispatch_calls, [False])
            self.assertEqual(runtime.activity("agent-a")["agent_states"][0]["agent_id"], "agent-a")

            connection.execute(
                "create table writes (thread_id text, checkpoint_ns text, channel text, checkpoint_id text, task_id text, idx integer, type text, value blob)"
            )
            for index, value in enumerate(
                [
                    runtime._serde.dumps_typed(HumanMessage(content=[{"text": "hello"}, {"reasoning": "because"}, "there"])),
                    runtime._serde.dumps_typed(Overwrite(value=[AIMessage(content="overwrite")])),
                    ("bad", b"not-valid"),
                ]
            ):
                type_name, payload = value
                connection.execute(
                    "insert into writes values (?, '', 'messages', ?, 'task', ?, ?, ?)",
                    (runtime.thread_id_factory.mention("thread", "agent-b"), f"checkpoint-{index}", index, type_name, payload),
                )
            connection.commit()

            activity = runtime.activity("agent-b")
            self.assertEqual(activity["private_messages"][0]["content"], "overwrite")
            self.assertEqual(runtime._message_summary({"role": "assistant", "content": [{"text": "dict text"}]})["content"], "dict text")
            self.assertEqual(runtime._content_text(["hello", {"reasoning": "because"}]), "hello\nbecause")
            self.assertEqual(runtime._content_text(None), "")
            self.assertEqual(runtime._content_text(123), "123")

    def test_mention_aware_team_requires_conversation_config(self) -> None:
        with self.assertRaisesRegex(ValueError, "top-level conversation"):
            MentionAwareTeam(
                team=team(agents={"agent-a": agent("agent-a", entrypoint=True)}),
                registry=FakeRegistry({}),
                checkpointer_handle=CheckpointerHandle("checkpointer"),
                root_dir=Path.cwd(),
                conversation_id="thread",
                thread_id_factory=ThreadIdFactory(),
                checkpoint_metadata_factory=CheckpointMetadataFactory(),
            )

    def _conversation_runtime(
        self,
        graphs: dict[str, FakeGraph],
        *,
        root: Path | None = None,
        connection: sqlite3.Connection | None = None,
    ) -> MentionAwareTeam:
        agents = {
            "agent-a": agent("agent-a", entrypoint=True),
            **{agent_id: agent(agent_id) for agent_id in graphs},
        }
        references = {
            "agent-a": conversation_reference(),
            **{agent_id: conversation_reference() for agent_id in graphs},
        }
        team_config = team(
            team_id="team",
            agents=agents,
            agent_references=references,
            conversation=TeamConversationSettings.from_mapping({}),
        )
        return MentionAwareTeam(
            team=team_config,
            registry=FakeRegistry(graphs),
            checkpointer_handle=CheckpointerHandle("checkpointer", connection),
            root_dir=root or Path.cwd(),
            conversation_id="thread",
            thread_id_factory=ThreadIdFactory(),
            checkpoint_metadata_factory=CheckpointMetadataFactory(),
        )


if __name__ == "__main__":
    unittest.main()
