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
    ConversationRun,
    ConversationRuntimeState,
    ConversationRuntimeController,
    ConversationStore,
    MentionAwareTeam,
    MentionParser,
    MentionRouter,
    PublicReplyExtractor,
)
from src.team_instanciator.conversation.dispatch_context import DispatchContext
from src.team_instanciator.conversation.conversation_control_event import ConversationControlEvent
from src.team_instanciator.conversation.conversation_model_attempt import ConversationModelAttempt
from src.team_instanciator.conversation.store import ORPHANED_RUN_DELIVERY_ERROR
from src.team_instanciator.conversation.thread_frontier import ThreadFrontier
from src.team_instanciator.runtime.thread_id_factory import ThreadIdFactory
from src.team_instanciator.runtime.tool_call_edge import ToolCallEdge
from src.team_instanciator.runtime.tool_call_edge_recorder import ToolCallEdgeRecorder
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
        self.async_calls = 0
        self.updates: list[tuple[Any, Any]] = []
        self.interrupted = False

    def invoke(self, input: Any, config: Any = None):
        self.calls.append((input, config))
        if self.callback is not None:
            self.callback(self, input, config)
        return {"messages": [AIMessage(content=self.response, id=f"msg-{len(self.calls)}")]}

    async def ainvoke(self, input: Any, config: Any = None):
        self.async_calls += 1
        return self.invoke(input, config=config)

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
    def _mention_thread_id(
        self,
        runtime: MentionAwareTeam,
        agent_id: str,
        *,
        branch_id: str = "branch_main",
    ) -> str:
        return runtime.thread_id_factory.mention(
            runtime.thread_id_factory.branch(runtime.root_thread_id, branch_id),
            agent_id,
        )

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
        run = ConversationRun(
            id="run",
            team_id="team",
            conversation_id="thread",
            branch_id="branch_main",
            agent_id="agent",
            logical_thread_key="thread:branch:branch_main:mention:agent",
            physical_thread_id="thread:branch:branch_main:mention:agent",
            status="running",
            started_at="now",
        )

        self.assertEqual(event.to_dict()["attachments"][0]["filename"], "notes.txt")
        self.assertEqual(state.to_dict()["agent_id"], "agent")
        self.assertTrue(runtime_state.to_dict()["mention_hook_enabled"])
        self.assertEqual(delivery.to_dict()["error"], "boom")
        self.assertEqual(interrupt.to_dict()["payload"]["action"], "write_file")
        self.assertEqual(run.to_dict()["commit_state"], "pending")
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
            connection.execute(
                """
                create table team_conversation_thread_frontiers (
                    team_id text not null,
                    conversation_id text not null,
                    frontier_id text not null,
                    branch_id text not null,
                    event_id text not null,
                    event_boundary text not null,
                    logical_thread_key text not null,
                    physical_thread_id text not null,
                    checkpoint_id text,
                    parent_logical_thread_key text,
                    usable_for_fork integer not null,
                    usable_for_continue integer not null,
                    created_at text not null,
                    primary key (team_id, conversation_id, frontier_id, event_boundary, logical_thread_key)
                )
                """
            )
            self._create_checkpoint_tables(connection)
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
            runner_thread_id = "thread:branch:branch_main:mention:runner"
            store.mark_run_started(
                "runner",
                run_id="run_runner",
                snapshot_seq=event.seq,
                branch_id="branch_main",
                logical_thread_key=runner_thread_id,
                physical_thread_id=runner_thread_id,
            )
            self.assertEqual(store.get_run("run_runner").commit_state, "pending")
            self._insert_checkpoint(
                connection,
                thread_id=runner_thread_id,
                checkpoint_id="checkpoint_runner",
                parent_checkpoint_id=None,
            )
            store.record_delivery(
                agent_id="runner",
                run_id="run_runner",
                snapshot_seq=event.seq,
                status="success",
                branch_id="branch_main",
            )
            branch = store.create_branch(
                label="Alternative",
                origin_checkpoint_id="checkpoint_01",
                head_checkpoint_id="checkpoint_01",
            )
            control_event = store.create_control_event(
                branch_id=branch.id,
                logical_thread_key="thread:mention:agent",
                physical_thread_id="thread:branch:branch_01:mention:agent",
                parent_run_id="run_01",
                kind="checkpoint-edit",
                content="replacement",
            )
            side_effect = store.record_external_side_effect(
                branch_id=branch.id,
                kind="file-write",
                target="/tmp/report.txt",
                audit_payload={"filename": "report.txt"},
                agent_id="agent",
            )
            interrupt = store.create_interrupt(
                kind="approve",
                payload={"action": "write_file"},
                run_id="run_01",
                agent_id="agent",
                checkpoint_id="checkpoint_01",
                branch_id=branch.id,
            )
            resolved = store.resume_interrupt(interrupt.id, decision="approve", response="ok", branch_id=branch.id)
            store.switch_branch(branch.id)

            reloaded = ConversationStore(team_id="team", conversation_id="thread", connection=connection)

            self.assertEqual(reloaded.list_events()[0].attachments[0].filename, "notes.txt")
            self.assertEqual(reloaded.list_events(through_seq=event.seq)[0].id, event.id)
            self.assertEqual(reloaded.get_runtime_state().mention_hook_enabled, False)
            self.assertEqual(reloaded.get_runtime_state().max_cascade_turns, 3)
            self.assertIsNone(reloaded.ensure_agent_state("agent").queued_after_seq)
            self.assertEqual(reloaded.ensure_agent_state("agent", branch_id="branch_main").queued_after_seq, event.seq)
            self.assertIn("boom", [delivery.error for delivery in reloaded.list_deliveries(branch_id="branch_main")])
            run = reloaded.get_run("run_runner")
            self.assertEqual(run.commit_state if run else None, "committed")
            self.assertEqual(run.stable_checkpoint_id if run else None, "checkpoint_runner")
            self.assertTrue(run.usable_for_fork if run else False)
            self.assertEqual(
                reloaded.latest_usable_run_checkpoint_id(
                    branch_id="branch_main",
                    logical_thread_key=runner_thread_id,
                    for_continue=True,
                ),
                "checkpoint_runner",
            )
            self.assertEqual(reloaded.list_deliveries(), [])
            self.assertEqual(reloaded.list_branches()[0].label, "Alternative")
            self.assertEqual(reloaded.list_control_events(branch_id=branch.id)[0].id, control_event.id)
            self.assertEqual(reloaded.list_control_events(branch_id=branch.id)[0].content, "replacement")
            self.assertEqual(reloaded.list_external_side_effects(branch_id=branch.id)[0].id, side_effect.id)
            self.assertTrue(reloaded.list_external_side_effects(branch_id=branch.id)[0].not_rewindable)
            self.assertEqual(reloaded.list_external_side_effects(branch_id=branch.id)[0].audit_payload["filename"], "report.txt")
            self.assertEqual(resolved.status if resolved else None, "resolved")
            self.assertEqual(reloaded.list_interrupts(), [])
            self.assertEqual(reloaded.list_interrupts(active_only=False)[0].decisions[0]["response"], "ok")
            self.assertEqual(reloaded.current_branch_id(), branch.id)
            self.assertIsNone(reloaded.switch_branch("missing"))
            self.assertIsNone(reloaded.switch_branch("branch_main"))
            self.assertEqual(reloaded.current_branch_id(), "branch_main")
            branch_columns = [row[1] for row in connection.execute("pragma table_info(team_conversation_branches)").fetchall()]
            self.assertIn("origin_event_id", branch_columns)
            self.assertIn("origin_logical_message_id", branch_columns)
            self.assertIn("origin_previous_event_id", branch_columns)
            frontier_columns = [row[1] for row in connection.execute("pragma table_info(team_conversation_thread_frontiers)").fetchall()]
            self.assertIn("run_id", frontier_columns)

    def test_store_reconciles_incomplete_commits_on_startup(self) -> None:
        with sqlite3.connect(":memory:", check_same_thread=False) as connection:
            store = ConversationStore(team_id="team", conversation_id="thread", connection=connection)
            event = store.append_event(author_id="human", author_kind="human", content="@agent please", mentions=("agent",))
            thread_id_factory = ThreadIdFactory()
            root_thread_id = thread_id_factory.root(team_id="team", conversation_id="thread")
            delivered_thread_id = thread_id_factory.mention(thread_id_factory.branch(root_thread_id, "branch_main"), "delivered")
            delivered_logical_key = thread_id_factory.logical_thread_key(delivered_thread_id)
            orphan_thread_id = thread_id_factory.mention(thread_id_factory.branch(root_thread_id, "branch_main"), "orphan")
            orphan_logical_key = thread_id_factory.logical_thread_key(orphan_thread_id)

            store.ensure_branch_thread(
                branch_id="branch_main",
                logical_thread_key=delivered_logical_key,
                physical_thread_id=delivered_thread_id,
                created_by_commit_id="run_delivered",
            )
            store.mark_run_started(
                "delivered",
                run_id="run_delivered",
                snapshot_seq=event.seq,
                branch_id="branch_main",
                logical_thread_key=delivered_logical_key,
                physical_thread_id=delivered_thread_id,
            )
            delivered_child_thread_id = f"{delivered_thread_id}:relation:rel_child:agent:child"
            delivered_child_logical_key = f"{delivered_logical_key}:relation:rel_child:agent:child"
            store.ensure_branch_thread(
                branch_id="branch_main",
                logical_thread_key=delivered_child_logical_key,
                physical_thread_id=delivered_child_thread_id,
                created_by_commit_id="commit_edge_delivered",
            )
            delivered_edge = ToolCallEdge(
                id="edge_delivered",
                team_id="team",
                conversation_id="thread",
                commit_id="commit_edge_delivered",
                branch_id="branch_main",
                parent_logical_thread_key=delivered_logical_key,
                parent_physical_thread_id=delivered_thread_id,
                relation_id="rel_child",
                target_agent_id="child",
                child_logical_thread_key=delivered_child_logical_key,
                child_physical_thread_id=delivered_child_thread_id,
                run_id="run_delivered",
                status="running",
            )
            ToolCallEdgeRecorder(connection).record_started(
                delivered_edge
            )
            ToolCallEdgeRecorder(connection).record_finished(delivered_edge, "success")
            connection.execute(
                """
                insert into team_conversation_deliveries (
                    team_id,
                    conversation_id,
                    branch_id,
                    id,
                    agent_id,
                    run_id,
                    snapshot_seq,
                    status,
                    created_at,
                    completed_at,
                    error
                )
                values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    "team",
                    "thread",
                    "branch_main",
                    "delivery_delivered",
                    "delivered",
                    "run_delivered",
                    event.seq,
                    "success",
                    "2026-06-05T00:00:00+00:00",
                    "2026-06-05T00:00:01+00:00",
                    None,
                ),
            )

            store.ensure_branch_thread(
                branch_id="branch_main",
                logical_thread_key=orphan_logical_key,
                physical_thread_id=orphan_thread_id,
                created_by_commit_id="run_orphan",
            )
            store.mark_run_started(
                "orphan",
                run_id="run_orphan",
                snapshot_seq=event.seq,
                branch_id="branch_main",
                logical_thread_key=orphan_logical_key,
                physical_thread_id=orphan_thread_id,
            )
            store.record_model_attempt_started(
                attempt_id="model_attempt_orphan",
                run_id="run_orphan",
                agent_id="orphan",
                provider="openai",
                model="openai:gpt-test",
                attempt_number=1,
                max_attempts=3,
                timeout_mode="stream_idle_timeout",
                timeout_seconds=120,
                branch_id="branch_main",
            )
            ToolCallEdgeRecorder(connection).record_started(
                ToolCallEdge(
                    id="edge_orphan",
                    team_id="team",
                    conversation_id="thread",
                    commit_id="commit_edge_orphan",
                    branch_id="branch_main",
                    parent_logical_thread_key="mention:parent",
                    parent_physical_thread_id=thread_id_factory.mention(thread_id_factory.branch(root_thread_id, "branch_main"), "parent"),
                    relation_id="rel_orphan",
                    target_agent_id="orphan",
                    child_logical_thread_key=orphan_logical_key,
                    child_physical_thread_id=orphan_thread_id,
                    run_id="run_orphan",
                    status="running",
                )
            )

            reloaded = ConversationStore(team_id="team", conversation_id="thread", connection=connection)
            delivered_run = reloaded.get_run("run_delivered")
            orphan_run = reloaded.get_run("run_orphan")

            self.assertEqual(delivered_run.commit_state if delivered_run else None, "committed")
            self.assertEqual(delivered_run.status if delivered_run else None, "success")
            self.assertFalse(reloaded.ensure_agent_state("delivered", branch_id="branch_main").running)
            self.assertIsNone(reloaded.ensure_agent_state("delivered", branch_id="branch_main").current_run_id)
            self.assertEqual(reloaded.ensure_agent_state("delivered", branch_id="branch_main").last_delivered_seq, event.seq)
            self.assertIsNotNone(
                reloaded.get_branch_thread(branch_id="branch_main", logical_thread_key=delivered_logical_key)
            )
            self.assertIsNotNone(
                reloaded.get_branch_thread(branch_id="branch_main", logical_thread_key=delivered_child_logical_key)
            )
            self.assertEqual(orphan_run.commit_state if orphan_run else None, "orphaned")
            self.assertEqual(orphan_run.stop_kind if orphan_run else None, "incomplete-commit")
            self.assertFalse(orphan_run.usable_for_continue if orphan_run else True)
            self.assertIsNone(reloaded.get_branch_thread(branch_id="branch_main", logical_thread_key=orphan_logical_key))
            self.assertEqual(
                [thread.status for thread in reloaded.list_branch_threads(branch_id="branch_main") if thread.logical_thread_key == orphan_logical_key],
                ["orphaned"],
            )
            self.assertFalse(reloaded.ensure_agent_state("orphan", branch_id="branch_main").running)
            self.assertIsNone(reloaded.ensure_agent_state("orphan", branch_id="branch_main").current_run_id)
            self.assertEqual(connection.execute("select status from tool_call_edges where id = 'edge_orphan'").fetchone()[0], "failed")
            orphan_delivery = [delivery for delivery in reloaded.list_deliveries(branch_id="branch_main") if delivery.run_id == "run_orphan"][0]
            self.assertEqual(orphan_delivery.status, "failed")
            self.assertEqual(orphan_delivery.error, ORPHANED_RUN_DELIVERY_ERROR)
            orphan_attempt = reloaded.get_model_attempt("model_attempt_orphan")
            self.assertEqual(orphan_attempt.status if orphan_attempt else None, "failed")
            self.assertEqual(orphan_attempt.normalized_failure_code if orphan_attempt else None, "process_interrupted")

            replacement = reloaded.ensure_branch_thread(
                branch_id="branch_main",
                logical_thread_key=orphan_thread_id,
                physical_thread_id=f"{orphan_thread_id}:retry",
                created_by_commit_id="run_retry",
            )
            self.assertEqual(replacement.status, "active")
            self.assertEqual(replacement.physical_thread_id, f"{orphan_thread_id}:retry")

    def test_store_deletes_legacy_unversioned_conversation_history(self) -> None:
        connection = sqlite3.connect(":memory:")
        connection.execute(
            """
            create table team_conversation_events (
                team_id text not null,
                conversation_id text not null,
                seq integer not null,
                id text not null,
                created_at text not null,
                author_id text not null,
                author_kind text not null,
                content text not null,
                mentions_json text not null,
                source_thread_id text,
                source_message_id text,
                metadata_json text not null,
                primary key (team_id, conversation_id, seq)
            )
            """
        )
        connection.execute(
            """
            insert into team_conversation_events (
                team_id,
                conversation_id,
                seq,
                id,
                created_at,
                author_id,
                author_kind,
                content,
                mentions_json,
                source_thread_id,
                source_message_id,
                metadata_json
            )
            values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            ("team", "thread", 1, "legacy_event", "2026-06-01T10:00:00Z", "human", "human", "legacy", "[]", None, None, "{}"),
        )
        connection.commit()

        store = ConversationStore(team_id="team", conversation_id="thread", connection=connection)

        self.assertEqual(store.list_events(), [])
        schema_row = connection.execute(
            """
            select history_schema_version
            from team_conversation_history_schema
            where team_id = 'team' and conversation_id = 'thread'
            """
        ).fetchone()
        self.assertEqual(schema_row[0], "branching.v1")

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

    def test_store_archives_branches_without_deleting_history(self) -> None:
        connection = sqlite3.connect(":memory:")
        store = ConversationStore(team_id="team", conversation_id="thread", connection=connection)

        branch = store.create_branch(label="Alternative", parent_branch_id="branch_main")
        archived = store.archive_branch(branch.id)
        reloaded = ConversationStore(team_id="team", conversation_id="thread", connection=connection)
        reloaded_archived = reloaded.archive_branch(branch.id)

        self.assertIsNotNone(archived)
        self.assertIsNotNone(archived.archived_at if archived else None)
        self.assertEqual(store.list_branches(), [])
        self.assertEqual([item.id for item in store.list_branches(include_archived=True)], [branch.id])
        self.assertEqual(reloaded_archived.archived_at if reloaded_archived else None, archived.archived_at if archived else None)
        self.assertIsNone(reloaded.switch_branch(branch.id))

        current = store.create_branch(label="Current", parent_branch_id="branch_main")
        store.switch_branch(current.id)
        with self.assertRaisesRegex(ValueError, "branch_main"):
            store.archive_branch("branch_main")
        with self.assertRaisesRegex(ValueError, "current branch"):
            store.archive_branch(current.id)

    def test_store_persists_studio_branch_ui_state_per_branch(self) -> None:
        connection = sqlite3.connect(":memory:")
        store = ConversationStore(team_id="team", conversation_id="thread", connection=connection)
        branch = store.create_branch(label="Edit", parent_branch_id="branch_main")

        main_state = store.save_studio_branch_ui_state(
            branch_id="branch_main",
            participant_id="human",
            draft_content="main draft",
            outbox_state=[{"clientMessageId": "main"}],
            editing_event_id="event_01",
        )
        branch_state = store.save_studio_branch_ui_state(
            branch_id=branch.id,
            participant_id="human",
            draft_content="branch draft",
            outbox_state=[],
            selected_agent_id="agent",
        )
        reloaded = ConversationStore(team_id="team", conversation_id="thread", connection=connection)

        self.assertEqual(main_state.branch_id, "branch_main")
        self.assertEqual(branch_state.branch_id, branch.id)
        self.assertEqual(reloaded.get_studio_branch_ui_state(branch_id="branch_main").draft_content, "main draft")
        self.assertEqual(reloaded.get_studio_branch_ui_state(branch_id="branch_main").editing_event_id, "event_01")
        self.assertEqual(reloaded.get_studio_branch_ui_state(branch_id=branch.id).draft_content, "branch draft")
        self.assertEqual(reloaded.get_studio_branch_ui_state(branch_id=branch.id).selected_agent_id, "agent")
        with self.assertRaisesRegex(ValueError, "participant_id"):
            store.save_studio_branch_ui_state(participant_id=" ")
        with self.assertRaisesRegex(ValueError, "outbox_state"):
            store.save_studio_branch_ui_state(outbox_state=[object()])  # type: ignore[list-item]

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

    def test_store_scopes_interrupts_to_current_branch(self) -> None:
        with sqlite3.connect(":memory:", check_same_thread=False) as connection:
            store = ConversationStore(team_id="team", conversation_id="thread", connection=connection)
            main_interrupt = store.create_interrupt(
                kind="approve",
                payload={"action": "main"},
                interrupt_id="interrupt_main",
            )
            branch = store.create_branch(label="Edit", parent_branch_id="branch_main")
            store.switch_branch(branch.id)
            branch_interrupt = store.create_interrupt(
                kind="approve",
                payload={"action": "branch"},
                interrupt_id="interrupt_branch",
            )

            self.assertEqual([interrupt.id for interrupt in store.list_interrupts()], [branch_interrupt.id])
            self.assertEqual([interrupt.id for interrupt in store.list_interrupts(branch_id="branch_main")], [main_interrupt.id])
            self.assertEqual(
                [interrupt.id for interrupt in store.list_interrupts(branch_id=None)],
                [main_interrupt.id, branch_interrupt.id],
            )
            self.assertIsNone(store.resume_interrupt(main_interrupt.id, decision="approve"))

            store.switch_branch("branch_main")
            resolved = store.resume_interrupt(main_interrupt.id, decision="approve")

            self.assertEqual(resolved.status if resolved else None, "resolved")
            self.assertEqual(store.list_interrupts(branch_id="branch_main"), [])
            self.assertEqual([interrupt.id for interrupt in store.list_interrupts(branch_id=branch.id)], [branch_interrupt.id])

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
        self.assertIsNone(controller.archive_branch("missing"))
        self.assertEqual(
            controller.get_studio_branch_ui_state(participant_id="human", branch_id=branch.id)["branch_id"],
            branch.id,
        )
        self.assertEqual(
            controller.save_studio_branch_ui_state(
                participant_id="human",
                branch_id=branch.id,
                draft_content="draft",
            )["draft_content"],
            "draft",
        )

        interrupt = controller.create_interrupt(kind="approve", payload={"action": "send"}, agent_id="agent")
        self.assertEqual(controller.list_interrupts()[0].id, interrupt.id)
        self.assertEqual(controller.resume_interrupt(interrupt.id, decision="approve").status, "resolved")
        branch_interrupt = controller.create_interrupt(
            kind="approve",
            payload={"action": "branch"},
            agent_id="agent",
            branch_id=branch.id,
        )
        self.assertEqual(controller.list_interrupts(branch_id=branch.id)[0].id, branch_interrupt.id)
        self.assertEqual(
            controller.resume_interrupt(branch_interrupt.id, decision="approve", branch_id=branch.id).status,
            "resolved",
        )

        edit_controller = ConversationRuntimeController(
            SimpleNamespace(
                edit_human_message=lambda event_id, content, **kwargs: (event_id, content, kwargs),
            )
        )

        self.assertEqual(
            edit_controller.edit_human_message("event_01", "edited", author_id="human", wait=False),
            ("event_01", "edited", {"author_id": "human", "wait": False}),
        )

    def test_runtime_value_objects_and_router_frontier_skip_edges(self) -> None:
        self.assertEqual(
            ConversationModelAttempt(
                id="attempt",
                team_id="team",
                conversation_id="thread",
                branch_id="branch_main",
                run_id="run",
                agent_id="agent",
                provider="openai",
                model="gpt",
                attempt_number=1,
                max_attempts=2,
                timeout_mode="stream",
                timeout_seconds=1.5,
                started_at="2026-06-01T10:00:00Z",
            ).to_dict()["status"],
            "running",
        )
        self.assertEqual(
            ThreadFrontier(
                frontier_id="frontier",
                team_id="team",
                conversation_id="thread",
                branch_id="branch_main",
                event_id="event",
                event_boundary="after",
                logical_thread_key="mention:agent",
                physical_thread_id="thread:branch:branch_main:mention:agent",
                checkpoint_id=None,
            ).to_dict()["frontier_id"],
            "frontier",
        )
        self.assertEqual(
            ConversationControlEvent(
                id="control",
                team_id="team",
                conversation_id="thread",
                branch_id="branch_main",
                logical_thread_key="mention:agent",
                physical_thread_id="thread:branch:branch_main:mention:agent",
                parent_run_id=None,
                kind="prompt-injection",
                content="continue",
                created_at="2026-06-01T10:00:00Z",
            ).to_dict()["kind"],
            "prompt-injection",
        )

        ToolCallEdgeRecorder(None).record_finished(
            ToolCallEdge(
                id="edge",
                team_id="team",
                conversation_id="thread",
                commit_id="commit_edge",
                branch_id="branch_main",
                parent_logical_thread_key="mention:parent",
                parent_physical_thread_id="parent-thread",
                relation_id="rel_child",
                target_agent_id="child",
                child_logical_thread_key="mention:child",
                child_physical_thread_id="child-thread",
                run_id=None,
                status="running",
            ),
            "success",
        )
        ToolCallEdgeRecorder(None)._initialize_sqlite()

        store = SimpleNamespace(
            list_tool_call_edges=lambda **_kwargs: [
                SimpleNamespace(
                    child_physical_thread_id="child-thread",
                    child_logical_thread_key="mention:child",
                    parent_logical_thread_key="mention:parent",
                )
            ],
            latest_checkpoint_id=lambda _thread_id: None,
            record_thread_frontier=lambda **_kwargs: (_ for _ in ()).throw(AssertionError("should skip")),
        )
        router = MentionRouter.__new__(MentionRouter)
        router._store = store

        router._record_tool_call_frontiers(
            frontier_id="frontier",
            event_id="event",
            branch_id="branch_main",
            run_id="run",
        )

    def test_checkpoint_resume_replays_graph_into_branch_scoped_event(self) -> None:
        graph = FakeGraph("resumed")
        runtime = self._conversation_runtime({"agent-b": graph})
        origin = runtime.store.append_event(
            author_id="human",
            author_kind="human",
            content="@agent-b original",
            mentions=("agent-b",),
        )
        thread_id = self._mention_thread_id(runtime, "agent-b")

        result = runtime.resume_checkpoint(
            checkpoint_id="checkpoint_01",
            checkpoint_ns="",
            thread_id=thread_id,
            mode="resume",
            origin_event_id=origin.id,
            origin_event_seq=origin.seq,
        )

        self.assertEqual(graph.calls[0][0], None)
        self.assertEqual(graph.calls[0][1]["configurable"]["checkpoint_id"], "checkpoint_01")
        self.assertEqual(result.event.metadata["branch_id"], result.branch.id)
        self.assertEqual(result.branch.origin_event_id, origin.id)
        self.assertEqual(result.branch.origin_logical_message_id, origin.logical_message_id)
        self.assertIsNone(result.branch.origin_previous_event_id)
        self.assertEqual(runtime.store.current_branch_id(), result.branch.id)

    def test_checkpoint_edit_updates_graph_state_before_replay(self) -> None:
        graph = FakeGraph("edited")
        runtime = self._conversation_runtime({"agent-b": graph})
        thread_id = self._mention_thread_id(runtime, "agent-b")

        result = runtime.runtime.resume_checkpoint(
            checkpoint_id="checkpoint_01",
            checkpoint_ns="",
            thread_id=thread_id,
            mode="edit",
            edited_content="replacement",
        )

        self.assertEqual(graph.updates[0][1]["messages"][0].content, "replacement")
        self.assertEqual(graph.calls[0][1]["configurable"]["checkpoint_id"], "fork-1")
        self.assertEqual(result.mode, "edit")
        self.assertEqual(runtime.store.list_control_events(branch_id=result.branch.id)[0].kind, "checkpoint-edit")
        self.assertEqual(runtime.store.list_control_events(branch_id=result.branch.id)[0].content, "replacement")
        self.assertEqual(
            [event.author_kind for event in runtime.store.list_events(branch_id=result.branch.id)],
            ["agent"],
        )

        with self.assertRaisesRegex(ValueError, "edited_content"):
            runtime.runtime.resume_checkpoint(
                checkpoint_id="checkpoint_01",
                checkpoint_ns="",
                thread_id=thread_id,
                mode="edit",
            )
        with self.assertRaisesRegex(ValueError, "mention thread"):
            runtime.resume_checkpoint(checkpoint_id="checkpoint_01", checkpoint_ns="", thread_id=runtime.root_thread_id)

        no_update = SimpleNamespace(invoke=lambda _input, config=None: {"messages": [AIMessage(content="ok")]})
        runtime.registry.graphs["agent-b"] = no_update
        with self.assertRaisesRegex(ValueError, "update_state"):
            runtime.resume_checkpoint(
                checkpoint_id="checkpoint_01",
                checkpoint_ns="",
                thread_id=thread_id,
                mode="edit",
                edited_content="replacement",
            )

        runtime.registry.graphs["agent-b"] = FakeGraph("")
        with self.assertRaisesRegex(ValueError, "no final textual"):
            runtime.resume_checkpoint(checkpoint_id="checkpoint_01", checkpoint_ns="", thread_id=thread_id)

        runtime.registry.graphs["agent-b"] = FakeGraph("regenerated")
        regenerated = runtime.resume_checkpoint(
            checkpoint_id="checkpoint_01",
            checkpoint_ns="",
            thread_id=thread_id,
            mode="regenerate",
        )
        self.assertEqual(regenerated.branch.label, "Checkpoint regenerate")

    def test_prompt_injection_after_stop_uses_usable_checkpoint_and_control_event(self) -> None:
        connection = sqlite3.connect(":memory:", check_same_thread=False)
        self._create_checkpoint_tables(connection)
        runtime_holder = {}

        def write_checkpoint(graph: FakeGraph, _input: Any, config: Any) -> None:
            thread_id = config["configurable"]["thread_id"]
            next_index = connection.execute("select count(*) from checkpoints").fetchone()[0] + 1
            checkpoint_id = f"checkpoint-{next_index}"
            parent_checkpoint_id = connection.execute(
                """
                select checkpoint_id
                from checkpoints
                where thread_id = ? and checkpoint_ns = ''
                order by checkpoint_id desc
                limit 1
                """,
                (thread_id,),
            ).fetchone()
            self._insert_checkpoint(
                connection,
                thread_id=thread_id,
                checkpoint_id=checkpoint_id,
                parent_checkpoint_id=parent_checkpoint_id[0] if parent_checkpoint_id is not None else None,
            )
            connection.commit()
            if len(graph.calls) == 1:
                runtime_holder["runtime"].runtime.stop_agent("agent-b")

        graph = FakeGraph("continued", callback=write_checkpoint)
        runtime = self._conversation_runtime({"agent-b": graph}, connection=connection)
        runtime_holder["runtime"] = runtime
        thread_id = self._mention_thread_id(runtime, "agent-b")

        stopped = runtime.append_human_message("@agent-b pause", author_id="mickael")
        injected = runtime.runtime.inject_agent_prompt("agent-b", "please continue")

        control_event = runtime.store.list_control_events(branch_id="branch_main")[0]
        deliveries = runtime.store.list_deliveries(branch_id="branch_main")
        checkpoints = connection.execute(
            """
            select checkpoint_id, parent_checkpoint_id
            from checkpoints
            where thread_id = ?
            order by checkpoint_id asc
            """,
            (thread_id,),
        ).fetchall()

        self.assertEqual(stopped.deliveries[0].status, "stopped")
        self.assertEqual(graph.updates[0][0]["configurable"]["checkpoint_id"], "checkpoint-1")
        self.assertEqual(graph.updates[0][1]["messages"][0].content, "please continue")
        self.assertEqual(graph.calls[1][0], None)
        self.assertEqual(graph.calls[1][1]["metadata"]["control_event_id"], control_event.id)
        self.assertEqual(control_event.kind, "prompt-injection")
        self.assertEqual(control_event.content, "please continue")
        self.assertEqual(control_event.branch_id, "branch_main")
        self.assertEqual(injected.event.content, "continued")
        self.assertEqual([delivery.status for delivery in deliveries], ["stopped", "success"])
        self.assertEqual(checkpoints, [("checkpoint-1", None), ("checkpoint-2", "checkpoint-1")])

    def test_prompt_injection_requires_usable_continue_frontier(self) -> None:
        runtime = self._conversation_runtime({"agent-b": FakeGraph("continued")})

        with self.assertRaisesRegex(ValueError, "content is required"):
            runtime.runtime.inject_agent_prompt("agent-b", " ")
        with self.assertRaisesRegex(ValueError, "usable checkpoint"):
            runtime.runtime.inject_agent_prompt("agent-b", "please continue")

    def test_prompt_injection_reports_graph_support_failures_and_empty_replies(self) -> None:
        runtime = self._conversation_runtime({"agent-b": FakeGraph("continued")})
        self._record_usable_frontier(runtime, "agent-b")
        runtime.registry.graphs["agent-b"] = SimpleNamespace(
            invoke=lambda _input, config=None: {"messages": [AIMessage(content="ok")]}
        )

        with self.assertRaisesRegex(ValueError, "update_state"):
            runtime.runtime.inject_agent_prompt("agent-b", "please continue")

        def fail_graph(_graph: FakeGraph, _input: Any, _config: Any) -> None:
            raise RuntimeError("graph failed")

        failing_runtime = self._conversation_runtime({"agent-b": FakeGraph("ignored", callback=fail_graph)})
        self._record_usable_frontier(failing_runtime, "agent-b")

        with self.assertRaisesRegex(RuntimeError, "graph failed"):
            failing_runtime.runtime.inject_agent_prompt("agent-b", "please continue")

        self.assertEqual(failing_runtime.store.list_deliveries()[0].status, "failed")

        empty_runtime = self._conversation_runtime({"agent-b": FakeGraph("")})
        self._record_usable_frontier(empty_runtime, "agent-b")

        with self.assertRaisesRegex(ValueError, "no final textual"):
            empty_runtime.runtime.inject_agent_prompt("agent-b", "please continue")

        self.assertEqual(empty_runtime.store.list_deliveries()[0].status, "empty")

    def test_team_private_scalar_and_checkpoint_timestamp_helpers(self) -> None:
        runtime = self._conversation_runtime({"agent-b": FakeGraph("answer")})
        list_type, list_value = runtime._serde.dumps_typed(["not mapping"])

        self.assertEqual(runtime._optional_int(5), 5)
        self.assertEqual(runtime._optional_int("42"), 42)
        self.assertIsNone(runtime._checkpoint_created_at(None, b"value"))
        self.assertIsNone(runtime._checkpoint_created_at("json", b"not json"))
        self.assertIsNone(runtime._checkpoint_created_at(list_type, list_value))

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
        target = agent("agent-b", description="Reviews implementation details.", toolsets=("scoped_read_tools",))

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
        self.assertIn("Attachments:", sync.messages[1].content)
        self.assertIn("filename: notes.txt", sync.messages[1].content)
        self.assertEqual(sync.messages[1].additional_kwargs["attachments"][0]["filename"], "notes.txt")
        self.assertEqual(
            sync.messages[1].additional_kwargs["attachments"][0]["read_path"],
            "/.coding-agents/conversations/team/thread/files/file-1",
        )
        self.assertIn(
            "read_path: /.coding-agents/conversations/team/thread/files/file-1",
            sync.messages[1].content,
        )

    def test_sync_builder_hides_attachment_read_paths_without_scoped_read_tools(self) -> None:
        store = ConversationStore(team_id="team", conversation_id="thread")
        event = store.append_event(
            author_id="human",
            author_kind="human",
            content="@agent-b see attached",
            mentions=("agent-b",),
            attachments=(
                ConversationFileRef(
                    id="file-1",
                    filename="notes.txt",
                    uri="conversation://files/file-1",
                    media_type="text/plain",
                    size_bytes=42,
                    added_by="human",
                ),
            ),
        )
        state = store.ensure_agent_state("agent-b")

        sync = AgentSyncBuilder(identity_refresh_after_tokens=10_000).build(
            target=agent("agent-b", description="Reviews implementation details."),
            state=state,
            events=[event],
        )

        attachment = sync.messages[1].additional_kwargs["attachments"][0]
        self.assertEqual(attachment["filename"], "notes.txt")
        self.assertNotIn("read_path", attachment)
        self.assertIn("Attachments:", sync.messages[1].content)
        self.assertIn("filename: notes.txt", sync.messages[1].content)
        self.assertIn("id: file-1", sync.messages[1].content)
        self.assertIn("uri: conversation://files/file-1", sync.messages[1].content)
        self.assertNotIn("read_path", sync.messages[1].content)

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

    def test_mention_aware_team_uses_branch_scoped_agent_threads_and_delivery_state(self) -> None:
        graph = FakeGraph("branch-aware reply")
        runtime = self._conversation_runtime({"agent-b": graph})

        first = runtime.append_human_message("@agent-b first", author_id="mickael").event
        branch = runtime.store.create_branch(label="Alternative", origin_event_seq=first.seq, origin_event_id=first.id)
        runtime.store.switch_branch(branch.id)
        second = runtime.append_human_message("@agent-b edited", author_id="mickael").event
        main_thread_id = self._mention_thread_id(runtime, "agent-b", branch_id="branch_main")
        branch_thread_id = self._mention_thread_id(runtime, "agent-b", branch_id=branch.id)

        self.assertEqual(graph.calls[0][1]["configurable"]["thread_id"], main_thread_id)
        self.assertEqual(graph.calls[1][1]["configurable"]["thread_id"], branch_thread_id)
        self.assertEqual(runtime.store.list_runs(branch_id="branch_main")[0].physical_thread_id, graph.calls[0][1]["configurable"]["thread_id"])
        self.assertEqual(runtime.store.list_runs(branch_id=branch.id)[0].physical_thread_id, graph.calls[1][1]["configurable"]["thread_id"])
        self.assertEqual(runtime.store.list_runs(branch_id=branch.id)[0].commit_state, "committed")
        self.assertEqual(runtime.store.ensure_agent_state("agent-b", branch_id="branch_main").last_delivered_seq, first.seq)
        self.assertEqual(runtime.store.ensure_agent_state("agent-b", branch_id=branch.id).last_delivered_seq, second.seq)
        self.assertEqual(
            [event.content for event in runtime.store.list_events(branch_id=branch.id)],
            ["@agent-b first", "@agent-b edited", "branch-aware reply"],
        )
        self.assertEqual(
            [event.content for event in runtime.store.list_events(branch_id="branch_main")],
            ["@agent-b first", "branch-aware reply"],
        )

    def test_mention_aware_team_edit_human_message_creates_version_branch_and_requeues_agents(self) -> None:
        graph = FakeGraph("edited reply")
        runtime = self._conversation_runtime({"agent-b": graph})
        first = runtime.append_human_message("hello", author_id="mickael").event
        original = runtime.append_human_message("@agent-b original", author_id="mickael").event

        edited = runtime.edit_human_message(original.id, "@agent-b edited", author_id="mickael")
        current_branch_id = runtime.store.current_branch_id()
        current_branch = next(branch for branch in runtime.store.list_branches() if branch.id == current_branch_id)
        current_events = runtime.store.list_events()
        main_events = runtime.store.list_events(branch_id="branch_main")

        self.assertNotEqual(current_branch_id, "branch_main")
        self.assertEqual(original.frontier_before_event_id, first.frontier_after_event_id)
        self.assertEqual(current_branch.origin_checkpoint_id, original.frontier_before_event_id)
        self.assertEqual(current_branch.origin_logical_message_id, original.logical_message_id)
        self.assertEqual(current_branch.origin_previous_event_id, first.id)
        self.assertEqual(edited.event.branch_id, current_branch_id)
        self.assertEqual(edited.event.logical_message_id, original.logical_message_id)
        self.assertEqual(edited.event.version_parent_event_id, original.id)
        self.assertEqual(edited.event.parent_event_id, first.id)
        self.assertEqual(edited.event.frontier_before_event_id, original.frontier_before_event_id)
        self.assertEqual([event.content for event in current_events], ["hello", "@agent-b edited", "edited reply"])
        self.assertEqual([event.content for event in main_events], ["hello", "@agent-b original", "edited reply"])
        self.assertEqual(graph.calls[0][1]["configurable"]["thread_id"], self._mention_thread_id(runtime, "agent-b", branch_id="branch_main"))
        self.assertEqual(graph.calls[1][1]["configurable"]["thread_id"], self._mention_thread_id(runtime, "agent-b", branch_id=current_branch_id))

        with self.assertRaisesRegex(ValueError, "only human"):
            runtime.edit_human_message(current_events[-1].id, "@agent-b invalid")
        with self.assertRaisesRegex(ValueError, "visible in the current branch"):
            runtime.edit_human_message("missing", "@agent-b invalid")

    def test_mention_aware_team_forks_mention_thread_from_prefork_frontier_checkpoint(self) -> None:
        connection = sqlite3.connect(":memory:", check_same_thread=False)
        self._create_checkpoint_tables(connection)
        checkpoint_lock = threading.Lock()

        def write_checkpoint(_graph: FakeGraph, _input: Any, config: Any) -> None:
            thread_id = config["configurable"]["thread_id"]
            with checkpoint_lock:
                next_index = connection.execute("select count(*) from checkpoints").fetchone()[0] + 1
                checkpoint_id = f"checkpoint-{next_index}"
                parent_checkpoint_id = connection.execute(
                    """
                    select checkpoint_id
                    from checkpoints
                    where thread_id = ? and checkpoint_ns = ''
                    order by checkpoint_id desc
                    limit 1
                    """,
                    (thread_id,),
                ).fetchone()
                self._insert_checkpoint(
                    connection,
                    thread_id=thread_id,
                    checkpoint_id=checkpoint_id,
                    parent_checkpoint_id=parent_checkpoint_id[0] if parent_checkpoint_id is not None else None,
                )
                self._insert_write(connection, thread_id=thread_id, checkpoint_id=checkpoint_id, value=f"write-{checkpoint_id}")
                connection.commit()

        graph = FakeGraph("checkpointed reply", callback=write_checkpoint)
        runtime = self._conversation_runtime({"agent-b": graph}, connection=connection)

        runtime.append_human_message("@agent-b first", author_id="mickael")
        original_second = runtime.append_human_message("@agent-b second", author_id="mickael").event
        runtime.edit_human_message(original_second.id, "@agent-b edited", author_id="mickael")

        main_thread_id = self._mention_thread_id(runtime, "agent-b", branch_id="branch_main")
        branch_thread_id = graph.calls[2][1]["configurable"]["thread_id"]
        branch_id = runtime.store.current_branch_id()
        branch_thread = runtime.store.list_branch_threads(branch_id=branch_id)[0]
        main_frontiers = runtime.store.list_thread_frontiers(branch_id="branch_main")
        branch_checkpoints = connection.execute(
            """
            select checkpoint_id, parent_checkpoint_id
            from checkpoints
            where thread_id = ?
            order by checkpoint_id asc
            """,
            (branch_thread_id,),
        ).fetchall()
        branch_writes = connection.execute(
            """
            select checkpoint_id, value
            from writes
            where thread_id = ?
            order by checkpoint_id asc
            """,
            (branch_thread_id,),
        ).fetchall()

        self.assertEqual([frontier.checkpoint_id for frontier in main_frontiers], ["checkpoint-1", "checkpoint-2"])
        self.assertEqual(branch_thread.physical_thread_id, branch_thread_id)
        self.assertEqual(branch_thread.logical_thread_key, "mention:agent-b")
        self.assertEqual(branch_thread.forked_from_branch_id, "branch_main")
        self.assertEqual(branch_thread.forked_from_thread_id, main_thread_id)
        self.assertEqual(branch_thread.forked_from_checkpoint_id, "checkpoint-1")
        self.assertEqual(branch_checkpoints[0], ("checkpoint-1", None))
        self.assertEqual(branch_checkpoints[1][1], "checkpoint-1")
        self.assertNotEqual(branch_checkpoints[1][0], "checkpoint-2")
        self.assertEqual(branch_writes[0], ("checkpoint-1", b"write-checkpoint-1"))
        self.assertEqual(branch_writes[1][0], branch_checkpoints[1][0])

    def test_mention_aware_team_forks_branch_created_from_raw_checkpoint_id(self) -> None:
        connection = sqlite3.connect(":memory:", check_same_thread=False)
        self._create_checkpoint_tables(connection)
        checkpoint_lock = threading.Lock()

        def write_checkpoint(_graph: FakeGraph, _input: Any, config: Any) -> None:
            thread_id = config["configurable"]["thread_id"]
            with checkpoint_lock:
                next_index = connection.execute("select count(*) from checkpoints").fetchone()[0] + 1
                checkpoint_id = f"checkpoint-{next_index}"
                parent_checkpoint_id = connection.execute(
                    """
                    select checkpoint_id
                    from checkpoints
                    where thread_id = ? and checkpoint_ns = ''
                    order by checkpoint_id desc
                    limit 1
                    """,
                    (thread_id,),
                ).fetchone()
                self._insert_checkpoint(
                    connection,
                    thread_id=thread_id,
                    checkpoint_id=checkpoint_id,
                    parent_checkpoint_id=parent_checkpoint_id[0] if parent_checkpoint_id is not None else None,
                )
                self._insert_write(connection, thread_id=thread_id, checkpoint_id=checkpoint_id, value=f"write-{checkpoint_id}")
                connection.commit()

        graph = FakeGraph("checkpointed reply", callback=write_checkpoint)
        runtime = self._conversation_runtime({"agent-b": graph}, connection=connection)

        runtime.append_human_message("@agent-b first", author_id="mickael")
        branch = runtime.store.create_branch(
            label="Checkpoint branch",
            origin_checkpoint_id="checkpoint-1",
            parent_branch_id="branch_main",
        )
        runtime.store.switch_branch(branch.id)
        runtime.append_human_message("@agent-b from checkpoint", author_id="mickael")

        branch_thread_id = graph.calls[1][1]["configurable"]["thread_id"]
        branch_thread = runtime.store.list_branch_threads(branch_id=branch.id)[0]
        branch_checkpoints = connection.execute(
            """
            select checkpoint_id, parent_checkpoint_id
            from checkpoints
            where thread_id = ?
            order by checkpoint_id asc
            """,
            (branch_thread_id,),
        ).fetchall()

        self.assertEqual(branch_thread.forked_from_branch_id, "branch_main")
        self.assertEqual(branch_thread.forked_from_checkpoint_id, "checkpoint-1")
        self.assertEqual(branch_checkpoints[0], ("checkpoint-1", None))
        self.assertEqual(branch_checkpoints[1][1], "checkpoint-1")

    def test_mention_aware_team_forks_from_terminal_empty_run_frontier(self) -> None:
        connection = sqlite3.connect(":memory:", check_same_thread=False)
        self._create_checkpoint_tables(connection)
        checkpoint_lock = threading.Lock()

        def write_checkpoint(_graph: FakeGraph, _input: Any, config: Any) -> None:
            thread_id = config["configurable"]["thread_id"]
            with checkpoint_lock:
                next_index = connection.execute("select count(*) from checkpoints").fetchone()[0] + 1
                checkpoint_id = f"checkpoint-{next_index}"
                parent_checkpoint_id = connection.execute(
                    """
                    select checkpoint_id
                    from checkpoints
                    where thread_id = ? and checkpoint_ns = ''
                    order by checkpoint_id desc
                    limit 1
                    """,
                    (thread_id,),
                ).fetchone()
                self._insert_checkpoint(
                    connection,
                    thread_id=thread_id,
                    checkpoint_id=checkpoint_id,
                    parent_checkpoint_id=parent_checkpoint_id[0] if parent_checkpoint_id is not None else None,
                )
                self._insert_write(connection, thread_id=thread_id, checkpoint_id=checkpoint_id, value=f"write-{checkpoint_id}")
                connection.commit()

        graph = FakeGraph("", callback=write_checkpoint)
        runtime = self._conversation_runtime({"agent-b": graph}, connection=connection)

        first = runtime.append_human_message("@agent-b empty", author_id="mickael").event
        original_second = runtime.append_human_message("@agent-b second", author_id="mickael").event
        runtime.edit_human_message(original_second.id, "@agent-b edited", author_id="mickael")

        branch_id = runtime.store.current_branch_id()
        branch_thread_id = graph.calls[2][1]["configurable"]["thread_id"]
        branch_thread = runtime.store.list_branch_threads(branch_id=branch_id)[0]
        main_frontiers = runtime.store.list_thread_frontiers(branch_id="branch_main")
        branch_checkpoints = connection.execute(
            """
            select checkpoint_id, parent_checkpoint_id
            from checkpoints
            where thread_id = ?
            order by checkpoint_id asc
            """,
            (branch_thread_id,),
        ).fetchall()

        self.assertEqual(
            [(frontier.event_id, frontier.checkpoint_id, frontier.usable_for_fork) for frontier in main_frontiers],
            [(first.id, "checkpoint-1", True), (original_second.id, "checkpoint-2", True)],
        )
        self.assertEqual(branch_thread.forked_from_branch_id, "branch_main")
        self.assertEqual(branch_thread.forked_from_checkpoint_id, "checkpoint-1")
        self.assertEqual(branch_checkpoints[0], ("checkpoint-1", None))
        self.assertEqual(branch_checkpoints[1][1], "checkpoint-1")

    def test_store_records_interrupted_terminal_run_frontier(self) -> None:
        connection = sqlite3.connect(":memory:", check_same_thread=False)
        self._create_checkpoint_tables(connection)
        store = ConversationStore(team_id="team", conversation_id="thread", connection=connection)
        event = store.append_event(
            author_id="human",
            author_kind="human",
            content="@agent-b pause",
            mentions=("agent-b",),
        )
        thread_id_factory = ThreadIdFactory()
        root_thread_id = thread_id_factory.root(team_id="team", conversation_id="thread")
        thread_id = thread_id_factory.mention(thread_id_factory.branch(root_thread_id, "branch_main"), "agent-b")
        store.mark_run_started(
            "agent-b",
            run_id="run_interrupted",
            snapshot_seq=event.seq,
            branch_id="branch_main",
            logical_thread_key=thread_id_factory.logical_thread_key(thread_id),
            physical_thread_id=thread_id,
        )
        self._insert_checkpoint(
            connection,
            thread_id=thread_id,
            checkpoint_id="checkpoint-interrupted",
            parent_checkpoint_id=None,
        )

        store.record_delivery(
            agent_id="agent-b",
            run_id="run_interrupted",
            snapshot_seq=event.seq,
            status="interrupted",
            branch_id="branch_main",
        )
        run = store.get_run("run_interrupted")
        frontiers = store.list_thread_frontiers(branch_id="branch_main")

        self.assertEqual(run.status if run else None, "interrupted")
        self.assertEqual(run.stable_checkpoint_id if run else None, "checkpoint-interrupted")
        self.assertTrue(run.usable_for_fork if run else False)
        self.assertTrue(run.usable_for_continue if run else False)
        self.assertEqual(frontiers[0].event_id, event.id)
        self.assertEqual(frontiers[0].event_boundary, "after")
        self.assertEqual(frontiers[0].checkpoint_id, "checkpoint-interrupted")
        self.assertEqual(frontiers[0].run_id, "run_interrupted")
        self.assertTrue(frontiers[0].usable_for_continue)

    def test_public_frontier_captures_five_nested_tool_threads_for_branch_fork(self) -> None:
        connection = sqlite3.connect(":memory:", check_same_thread=False)
        self._create_checkpoint_tables(connection)

        def create_nested_edges(_graph: FakeGraph, _input: Any, config: Any) -> None:
            metadata = config["metadata"]
            run_id = metadata["run_id"]
            branch_id = metadata["branch_id"]
            parent_logical_thread_key = metadata["logical_thread_key"]
            parent_physical_thread_id = metadata["physical_thread_id"]
            recorder = ToolCallEdgeRecorder(connection)
            self._insert_checkpoint(
                connection,
                thread_id=parent_physical_thread_id,
                checkpoint_id="checkpoint-parent",
                parent_checkpoint_id=None,
            )
            for level in range(1, 6):
                child_logical_thread_key = f"{parent_logical_thread_key}:relation:rel_level_{level}:agent:agent-{level}"
                child_physical_thread_id = f"{parent_physical_thread_id}:relation:rel_level_{level}:agent:agent-{level}"
                edge_id = f"edge_level_{level}"
                recorder.record_started(
                    edge := ToolCallEdge(
                        id=edge_id,
                        team_id="team",
                        conversation_id="thread",
                        commit_id=f"commit_{edge_id}",
                        branch_id=branch_id,
                        parent_logical_thread_key=parent_logical_thread_key,
                        parent_physical_thread_id=parent_physical_thread_id,
                        relation_id=f"rel_level_{level}",
                        target_agent_id=f"agent-{level}",
                        child_logical_thread_key=child_logical_thread_key,
                        child_physical_thread_id=child_physical_thread_id,
                        run_id=run_id,
                        status="running",
                    )
                )
                recorder.record_finished(edge, "success")
                self._insert_checkpoint(
                    connection,
                    thread_id=child_physical_thread_id,
                    checkpoint_id=f"checkpoint-level-{level}",
                    parent_checkpoint_id=None,
                )
                parent_logical_thread_key = child_logical_thread_key
                parent_physical_thread_id = child_physical_thread_id
            connection.commit()

        graph = FakeGraph("public reply", callback=create_nested_edges)
        runtime = self._conversation_runtime({"agent-b": graph}, connection=connection)

        runtime.append_human_message("@agent-b first", author_id="mickael")
        original_second = runtime.append_human_message("second", author_id="mickael").event
        first_reply = [event for event in runtime.store.list_events() if event.author_kind == "agent"][0]
        first_reply_frontiers = [
            frontier
            for frontier in runtime.store.list_thread_frontiers(branch_id="branch_main")
            if frontier.frontier_id == first_reply.frontier_after_event_id
        ]
        level_five_frontier = next(
            frontier
            for frontier in first_reply_frontiers
            if frontier.logical_thread_key.endswith(":relation:rel_level_5:agent:agent-5")
        )

        runtime.edit_human_message(original_second.id, "second edited", author_id="mickael")
        branch_id = runtime.store.current_branch_id()
        level_five_branch_thread = runtime.store.ensure_branch_thread(
            branch_id=branch_id,
            logical_thread_key=level_five_frontier.logical_thread_key,
            physical_thread_id=(
                f"{self._mention_thread_id(runtime, 'agent-b', branch_id=branch_id)}"
                ":relation:rel_level_1:agent:agent-1"
                ":relation:rel_level_2:agent:agent-2"
                ":relation:rel_level_3:agent:agent-3"
                ":relation:rel_level_4:agent:agent-4"
                ":relation:rel_level_5:agent:agent-5"
            ),
        )

        self.assertEqual(len(first_reply_frontiers), 6)
        self.assertEqual({frontier.run_id for frontier in first_reply_frontiers}, {graph.calls[0][1]["metadata"]["run_id"]})
        self.assertEqual(level_five_frontier.checkpoint_id, "checkpoint-level-5")
        self.assertEqual(level_five_frontier.parent_logical_thread_key, "mention:agent-b:relation:rel_level_1:agent:agent-1:relation:rel_level_2:agent:agent-2:relation:rel_level_3:agent:agent-3:relation:rel_level_4:agent:agent-4")
        self.assertEqual(level_five_branch_thread.forked_from_branch_id, "branch_main")
        self.assertEqual(level_five_branch_thread.forked_from_checkpoint_id, "checkpoint-level-5")

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
            self.assertTrue((root / ".coding-agents" / "conversations" / "team" / "thread" / "files" / attachment["id"]).is_file())

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

    def test_queued_mentions_stay_paused_when_switching_away_from_branch(self) -> None:
        graph = FakeGraph("answer")
        runtime = self._conversation_runtime({"agent-b": graph})
        event = runtime.store.append_event(
            author_id="human",
            author_kind="human",
            content="@agent-b queued",
            mentions=("agent-b",),
        )
        runtime.router.enqueue_targets(event, ("agent-b",))
        branch = runtime.store.create_branch(label="Alternative", parent_branch_id="branch_main")
        runtime.store.switch_branch(branch.id)

        runtime.router.drain()

        self.assertEqual(graph.calls, [])
        self.assertTrue(runtime.store.ensure_agent_state("agent-b", branch_id="branch_main").queued)
        self.assertFalse(runtime.store.ensure_agent_state("agent-b", branch_id=branch.id).queued)

        runtime.store.switch_branch("branch_main")
        runtime.router.drain()

        self.assertEqual(len(graph.calls), 1)
        self.assertEqual(graph.calls[0][1]["metadata"]["branch_id"], "branch_main")
        self.assertFalse(runtime.store.ensure_agent_state("agent-b", branch_id="branch_main").queued)

    def test_dispatch_pending_drains_existing_queue_when_hook_is_enabled(self) -> None:
        graph = FakeGraph("answer")
        runtime = self._conversation_runtime({"agent-b": graph})
        event = runtime.store.append_event(
            author_id="human",
            author_kind="human",
            content="@agent-b queued",
            mentions=("agent-b",),
        )
        runtime.router.enqueue_targets(event, ("agent-b",))

        runtime.dispatch_pending(wait=True)

        self.assertEqual(len(graph.calls), 1)
        self.assertFalse(runtime.store.ensure_agent_state("agent-b").queued)

    def test_router_uses_async_graph_invocation_when_available(self) -> None:
        graph = FakeGraph("answer")
        runtime = self._conversation_runtime({"agent-b": graph})

        runtime.append_human_message("@agent-b hello", wait=True)

        self.assertEqual(graph.async_calls, 1)

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
            source_thread_id=self._mention_thread_id(runtime, "agent-b"),
            source_message_id=None,
            branch_id="branch_main",
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
            markdown_ref = runtime.create_public_file_ref(filename="SKILL.md", content=b"# skill", added_by="human")
            mdc_ref = runtime.create_public_file_ref(filename="agent.mdc", content=b"---\n---\n", added_by="human")
            runtime.append_agent_message(agent_id="agent-b", content="@agent-b self ignored")
            runtime.append_agent_message(agent_id="agent-b", content="@agent-b no hook")
            dispatch_calls = []
            runtime.router.dispatch = lambda wait=False: dispatch_calls.append(wait)
            runtime.append_agent_message(agent_id="agent-b", content="@agent-b asks @agent-b and @agent-b")
            runtime.append_agent_message(agent_id="agent-b", content="@agent-a hello")
            runtime.wait_for_idle()

            self.assertEqual(dict_ref_event.attachments[0].id, "dict-file")
            self.assertEqual(public_ref.size_bytes, 5)
            self.assertEqual(markdown_ref.media_type, "text/markdown")
            self.assertEqual(mdc_ref.media_type, "text/markdown")
            side_effect = runtime.store.list_external_side_effects()[0]
            self.assertEqual(side_effect.branch_id, "branch_main")
            self.assertEqual(side_effect.kind, "file-write")
            self.assertEqual(side_effect.audit_payload["file_id"], public_ref.id)
            self.assertTrue(side_effect.not_rewindable)
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
                    (
                        self._mention_thread_id(runtime, "agent-b"),
                        f"checkpoint-{index}",
                        index,
                        type_name,
                        payload,
                    ),
                )
            connection.commit()

            activity = runtime.activity("agent-b")
            self.assertEqual(activity["private_messages"][0]["content"], "overwrite")
            self.assertEqual(runtime._message_summary({"role": "assistant", "content": [{"text": "dict text"}]})["content"], "dict text")
            self.assertEqual(runtime._content_text(["hello", {"reasoning": "because"}]), "hello\nbecause")
            self.assertEqual(runtime._content_text(None), "")
            self.assertEqual(runtime._content_text(123), "123")

    def test_mention_aware_team_activity_private_messages_include_checkpoint_created_at(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            connection = sqlite3.connect(":memory:", check_same_thread=False)
            runtime = self._conversation_runtime({"agent-b": FakeGraph("answer")}, root=root, connection=connection)
            thread_id = self._mention_thread_id(runtime, "agent-b")
            checkpoint_type, checkpoint_blob = runtime._serde.dumps_typed(
                {"id": "checkpoint-1", "ts": "2026-06-01T10:00:02+00:00"}
            )
            message_type, message_blob = runtime._serde.dumps_typed(AIMessage(content="working", id="message-1"))

            connection.execute(
                """
                create table checkpoints (
                    thread_id text not null,
                    checkpoint_ns text not null default '',
                    checkpoint_id text not null,
                    parent_checkpoint_id text,
                    type text,
                    checkpoint blob,
                    metadata blob,
                    primary key (thread_id, checkpoint_ns, checkpoint_id)
                )
                """
            )
            connection.execute(
                """
                create table writes (
                    thread_id text not null,
                    checkpoint_ns text not null default '',
                    checkpoint_id text not null,
                    task_id text not null,
                    idx integer not null,
                    channel text not null,
                    type text,
                    value blob,
                    primary key (thread_id, checkpoint_ns, checkpoint_id, task_id, idx)
                )
                """
            )
            connection.execute(
                """
                insert into checkpoints (
                    thread_id, checkpoint_ns, checkpoint_id, parent_checkpoint_id, type, checkpoint, metadata
                )
                values (?, '', 'checkpoint-1', null, ?, ?, null)
                """,
                (thread_id, checkpoint_type, checkpoint_blob),
            )
            connection.execute(
                """
                insert into writes (thread_id, checkpoint_ns, checkpoint_id, task_id, idx, channel, type, value)
                values (?, '', 'checkpoint-1', 'task', 0, 'messages', ?, ?)
                """,
                (thread_id, message_type, message_blob),
            )
            connection.commit()

            activity = runtime.activity("agent-b")

            self.assertEqual(activity["private_messages"][0]["content"], "working")
            self.assertEqual(activity["private_messages"][0]["created_at"], "2026-06-01T10:00:02Z")

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

    def _create_checkpoint_tables(self, connection: sqlite3.Connection) -> None:
        connection.execute(
            """
            create table checkpoints (
                thread_id text not null,
                checkpoint_ns text not null default '',
                checkpoint_id text not null,
                parent_checkpoint_id text,
                type text,
                checkpoint blob,
                metadata blob,
                primary key (thread_id, checkpoint_ns, checkpoint_id)
            )
            """
        )
        connection.execute(
            """
            create table writes (
                thread_id text not null,
                checkpoint_ns text not null default '',
                checkpoint_id text not null,
                task_id text not null,
                idx integer not null,
                channel text not null,
                type text,
                value blob,
                primary key (thread_id, checkpoint_ns, checkpoint_id, task_id, idx)
            )
            """
        )

    def _insert_checkpoint(
        self,
        connection: sqlite3.Connection,
        *,
        thread_id: str,
        checkpoint_id: str,
        parent_checkpoint_id: str | None,
    ) -> None:
        connection.execute(
            """
            insert into checkpoints (
                thread_id,
                checkpoint_ns,
                checkpoint_id,
                parent_checkpoint_id,
                type,
                checkpoint,
                metadata
            )
            values (?, '', ?, ?, 'bytes', ?, ?)
            """,
            (thread_id, checkpoint_id, parent_checkpoint_id, b"checkpoint", b"metadata"),
        )

    def _insert_write(
        self,
        connection: sqlite3.Connection,
        *,
        thread_id: str,
        checkpoint_id: str,
        value: str,
    ) -> None:
        connection.execute(
            """
            insert into writes (
                thread_id,
                checkpoint_ns,
                checkpoint_id,
                task_id,
                idx,
                channel,
                type,
                value
            )
            values (?, '', ?, 'task', 0, 'messages', 'bytes', ?)
            """,
            (thread_id, checkpoint_id, value.encode("utf-8")),
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

    def _record_usable_frontier(self, runtime: MentionAwareTeam, agent_id: str) -> None:
        physical_thread_id = self._mention_thread_id(runtime, agent_id)
        runtime.store.record_thread_frontier(
            frontier_id=f"frontier_{agent_id}",
            branch_id="branch_main",
            event_id="event_01",
            event_boundary="after",
            logical_thread_key=runtime.thread_id_factory.logical_thread_key(physical_thread_id),
            physical_thread_id=physical_thread_id,
            checkpoint_id=f"checkpoint_{agent_id}",
            usable_for_continue=True,
        )


if __name__ == "__main__":
    unittest.main()
