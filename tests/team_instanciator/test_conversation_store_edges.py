from __future__ import annotations

import sqlite3
import unittest

from src.team_instanciator.conversation.store import ConversationStore
from src.team_instanciator.runtime.thread_id_factory import ThreadIdFactory
from src.team_instanciator.runtime.tool_call_edge import ToolCallEdge
from src.team_instanciator.runtime.tool_call_edge_recorder import ToolCallEdgeRecorder


class ConversationStoreEdgeTests(unittest.TestCase):
    def test_shared_sqlite_scopes_tool_edges_and_thread_ids_by_team(self) -> None:
        with sqlite3.connect(":memory:", check_same_thread=False) as connection:
            alpha = ConversationStore(team_id="alpha", conversation_id="thread", connection=connection)
            beta = ConversationStore(team_id="beta", conversation_id="thread", connection=connection)
            thread_factory = ThreadIdFactory()
            alpha_thread_id = thread_factory.mention(
                thread_factory.branch(thread_factory.root(team_id="alpha", conversation_id="thread"), "branch_main"),
                "agent",
            )
            beta_thread_id = thread_factory.mention(
                thread_factory.branch(thread_factory.root(team_id="beta", conversation_id="thread"), "branch_main"),
                "agent",
            )
            recorder = ToolCallEdgeRecorder(connection)

            self.assertNotEqual(alpha_thread_id, beta_thread_id)

            alpha_edge = ToolCallEdge(
                id="call_shared",
                team_id="alpha",
                conversation_id="thread",
                commit_id="commit_alpha",
                branch_id="branch_main",
                parent_logical_thread_key="mention:agent",
                parent_physical_thread_id=alpha_thread_id,
                relation_id="rel_worker",
                target_agent_id="worker",
                child_logical_thread_key="mention:agent:relation:rel_worker:agent:worker",
                child_physical_thread_id=f"{alpha_thread_id}:relation:rel_worker:agent:worker",
                run_id="run_alpha",
                status="running",
            )
            beta_edge = ToolCallEdge(
                id="call_shared",
                team_id="beta",
                conversation_id="thread",
                commit_id="commit_beta",
                branch_id="branch_main",
                parent_logical_thread_key="mention:agent",
                parent_physical_thread_id=beta_thread_id,
                relation_id="rel_worker",
                target_agent_id="worker",
                child_logical_thread_key="mention:agent:relation:rel_worker:agent:worker",
                child_physical_thread_id=f"{beta_thread_id}:relation:rel_worker:agent:worker",
                run_id="run_beta",
                status="running",
            )

            recorder.record_started(alpha_edge)
            recorder.record_started(beta_edge)
            recorder.record_finished(alpha_edge, "success")
            recorder.record_finished(beta_edge, "failed")

            self.assertEqual(
                connection.execute(
                    "select team_id, status from tool_call_edges where id = 'call_shared' order by team_id"
                ).fetchall(),
                [("alpha", "success"), ("beta", "failed")],
            )
            self.assertEqual(
                [edge.commit_id for edge in alpha.list_tool_call_edges(branch_id="branch_main", run_id="run_alpha")],
                ["commit_alpha"],
            )
            self.assertEqual(
                [edge.commit_id for edge in beta.list_tool_call_edges(branch_id="branch_main", run_id="run_beta")],
                ["commit_beta"],
            )

    def test_in_memory_lookup_frontier_side_effect_and_schema_fallbacks(self) -> None:
        store = ConversationStore(team_id="team", conversation_id="thread")
        event = store.append_event(author_id="human", author_kind="human", content="@agent")

        self.assertEqual(store._committed_causal_commit_ids({"run"}), {"run"})
        self.assertIsNone(store.get_event("missing"))
        self.assertIsNone(
            store.record_model_attempt_finished(
                "missing",
                status="not-a-status",
            )
        )
        attempt = store.record_model_attempt_started(
            attempt_id="attempt",
            run_id="run_model",
            agent_id="agent",
            provider="openai",
            model="gpt",
            attempt_number=1,
            max_attempts=2,
            timeout_mode="stream",
            timeout_seconds=1.0,
        )
        finished_attempt = store.record_model_attempt_finished(attempt.id, status="success")

        self.assertEqual(finished_attempt.status, "success")
        self.assertEqual(store.get_model_attempt(attempt.id).status, "success")
        self.assertIsNone(store.record_model_attempt_finished("missing", status="success"))

        frontier = store.record_thread_frontier(
            frontier_id="frontier",
            branch_id="branch_main",
            event_id=event.id,
            event_boundary="after",
            logical_thread_key="mention:agent",
            physical_thread_id="thread:branch:branch_main:mention:agent",
            checkpoint_id=None,
        )

        self.assertEqual(frontier.frontier_id, "frontier")
        self.assertEqual(
            store.get_thread_frontier(
                frontier_id="frontier",
                branch_id="branch_main",
                logical_thread_key="mention:agent",
            ).frontier_id,
            "frontier",
        )
        self.assertIsNone(
            store.get_thread_frontier(
                frontier_id="missing",
                branch_id="branch_main",
                logical_thread_key="mention:agent",
            )
        )

        with self.assertRaisesRegex(ValueError, "JSON-serializable"):
            store.record_external_side_effect(kind="write", target="file", audit_payload={"bad": object()})

        side_effect = store.record_external_side_effect(kind="write", target="file", audit_payload={"ok": True})

        self.assertEqual(side_effect.audit_payload, {"ok": True})
        self.assertIsNone(
            store.latest_usable_run_checkpoint_id(
                branch_id="branch_main",
                logical_thread_key="mention:agent",
                for_continue=True,
            )
        )

        delivery = store.record_delivery(agent_id="agent", run_id="run_missing", snapshot_seq=1, status="success")

        self.assertEqual(store.get_run("run_missing").id, delivery.run_id)
        self.assertEqual(store._latest_delivery_for_run("run_missing").id, delivery.id)
        self.assertIsNone(store._latest_visible_event_through_seq("branch_main", None))
        self.assertTrue(store._event_visible_in_branch(event, None))
        self.assertFalse(store._event_visible_in_branch_id(event, "branch_other", {"branch_other"}))
        self.assertFalse(store._event_visible_in_branch_id(event, "branch_missing", set()))

        store._ensure_column("missing", "column", "text")
        store._ensure_branch_aware_history_schema()
        self.assertFalse(store._has_persisted_conversation_history())
        store._delete_persisted_conversation_history()
        store._upsert_history_schema_version()
        store._ensure_branch_scoped_agent_state()
        store._ensure_tool_call_edges_schema()
        self.assertFalse(store._table_exists("team_conversation_events"))

    def test_sqlite_tool_call_edges_schema_is_recreated_when_unscoped(self) -> None:
        with sqlite3.connect(":memory:", check_same_thread=False) as connection:
            connection.execute("create table tool_call_edges (id text primary key, commit_id text not null)")

            ConversationStore(team_id="team", conversation_id="thread", connection=connection)

            columns = {str(row[1]) for row in connection.execute("pragma table_info(tool_call_edges)").fetchall()}
            self.assertIn("team_id", columns)
            self.assertIn("conversation_id", columns)

    def test_sqlite_missing_event_unstable_delivery_branch_thread_and_legacy_agent_state(self) -> None:
        with sqlite3.connect(":memory:", check_same_thread=False) as connection:
            store = ConversationStore(team_id="team", conversation_id="thread", connection=connection)

            self.assertIsNone(store.get_event("missing"))

            store.mark_run_started(
                "agent",
                run_id="run_failed",
                snapshot_seq=1,
                branch_id="branch_main",
                logical_thread_key="mention:agent",
                physical_thread_id="thread:branch:branch_main:mention:agent",
            )
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
                insert into checkpoints (thread_id, checkpoint_ns, checkpoint_id, parent_checkpoint_id, type, checkpoint, metadata)
                values (?, '', 'checkpoint_01', null, null, null, null)
                """,
                ("thread:branch:branch_main:mention:agent",),
            )

            delivery = store.record_delivery(agent_id="agent", run_id="run_failed", snapshot_seq=1, status="failed")
            run = store.get_run("run_failed")

            self.assertEqual(delivery.status, "failed")
            self.assertEqual(run.latest_checkpoint_id, "checkpoint_01")
            self.assertEqual(run.checkpoint_stability, "unstable")

            branch = store.create_branch(label="Alternative", origin_checkpoint_id="checkpoint_missing")
            branch_thread = store.ensure_branch_thread(
                branch_id=branch.id,
                logical_thread_key="mention:agent",
                physical_thread_id="thread:branch:branch_alt:mention:agent",
            )

            self.assertIsNone(branch_thread.forked_from_checkpoint_id)

        with sqlite3.connect(":memory:", check_same_thread=False) as legacy_connection:
            legacy_connection.execute(
                """
                create table team_conversation_agent_state (
                    team_id text not null,
                    conversation_id text not null,
                    agent_id text not null,
                    last_delivered_seq integer not null,
                    running integer not null,
                    queued integer not null,
                    queued_after_seq integer,
                    current_run_id text,
                    current_snapshot_seq integer,
                    stop_requested integer not null,
                    last_identity_refresh_seq integer not null,
                    token_estimate_since_identity_refresh integer not null,
                    primary key (team_id, conversation_id, agent_id)
                )
                """
            )
            legacy_connection.execute(
                """
                insert into team_conversation_agent_state (
                    team_id,
                    conversation_id,
                    agent_id,
                    last_delivered_seq,
                    running,
                    queued,
                    queued_after_seq,
                    current_run_id,
                    current_snapshot_seq,
                    stop_requested,
                    last_identity_refresh_seq,
                    token_estimate_since_identity_refresh
                ) values ('team', 'thread', 'agent', 3, 0, 0, null, null, null, 0, 2, 7)
                """
            )

            migrated_store = ConversationStore(team_id="team", conversation_id="thread", connection=legacy_connection)

            self.assertEqual(migrated_store.get_agent_state("agent").branch_id, "branch_main")


if __name__ == "__main__":
    unittest.main()
