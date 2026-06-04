from __future__ import annotations

import asyncio
import base64
import io
import json
import runpy
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from fastapi.testclient import TestClient
from langchain_core.messages import AIMessage
from langgraph.checkpoint.serde.jsonplus import JsonPlusSerializer

from src.team_instanciator.conversation import ConversationEvent, ConversationStore
from src.webapp_studio.backend.api.checkpoint_history_reader import CheckpointHistoryReader
from src.webapp_studio.backend.api.redactor import redact_sensitive_fields
from src.webapp_studio.backend.api.studio_attachment_ref_factory import (
    MAX_ATTACHMENT_BYTES,
    StudioAttachmentRefFactory,
)
from src.webapp_studio.backend.api.studio_api_controller import StudioApiController
from src.webapp_studio.backend.api.studio_state_factory import StudioStateFactory
from src.webapp_studio.backend.application.studio_backend_launcher import StudioBackendLauncher
from src.webapp_studio.backend.contracts.branch_create_request import BranchCreateRequest
from src.webapp_studio.backend.contracts.checkpoint_summary import CheckpointSummary
from src.webapp_studio.backend.contracts.conversation_delivery_dto import ConversationDeliveryDto
from src.webapp_studio.backend.contracts.runtime_update_request import RuntimeUpdateRequest
from src.webapp_studio.backend.server import (
    CONTENT_SECURITY_POLICY,
    _produce_stream_events,
    _stream_events,
    create_app,
    main,
    parse_args,
)
from src.webapp_studio.backend.streaming.stream_buffer import StreamBuffer
from src.webapp_studio.backend.streaming.stream_client_queue import StreamClientQueue


class _RejectingStreamQueue:
    def __init__(self, reject_on: int) -> None:
        self.reject_on = reject_on
        self.puts = 0
        self.closed = False

    async def put(self, frame: str) -> bool:
        self.puts += 1
        if self.puts == self.reject_on:
            return False
        return True

    def close(self) -> None:
        self.closed = True


class BackendApiTests(unittest.TestCase):
    def test_studio_endpoints_return_versioned_envelopes_and_publish_events(self) -> None:
        fake = self._fake_conversation()
        buffer = StreamBuffer()
        client = TestClient(create_app(fake, stream_buffer=buffer))

        root_health_response = client.get("/health")
        root_health = root_health_response.json()
        health_response = client.get("/api/studio/v1/health")
        health = health_response.json()
        state = client.get("/api/studio/v1/state").json()
        activity = client.get("/api/studio/v1/activity?agent_id=agent").json()
        message = client.post("/api/studio/v1/messages", json={"content": "@agent hello", "author_id": "human"}).json()
        runtime = client.patch("/api/studio/v1/runtime", json={"mention_hook_enabled": False, "max_cascade_turns": None}).json()
        stopped = client.post("/api/studio/v1/agents/agent/stop").json()
        runs = client.get("/api/studio/v1/runs").json()
        joined = client.post("/api/studio/v1/runs/run_01/join").json()
        missing_run_join = client.post("/api/studio/v1/runs/run_missing/join").json()
        queue = client.get("/api/studio/v1/queue").json()
        checkpoints = client.get("/api/studio/v1/checkpoints").json()
        checkpoint = client.get("/api/studio/v1/checkpoints/missing").json()
        branches = client.get("/api/studio/v1/branches").json()
        switched = client.post("/api/studio/v1/branches/branch_main/switch").json()
        interrupts = client.get("/api/studio/v1/interrupts").json()
        missing_file = client.get("/api/studio/v1/files/file_missing").json()
        missing_queue = client.delete("/api/studio/v1/queue/queue_thread_agent").json()

        self.assertEqual(root_health["schema_version"], "studio.v1")
        self.assertEqual(health["schema_version"], "studio.v1")
        self.assertEqual(root_health_response.headers["x-content-type-options"], "nosniff")
        self.assertEqual(root_health_response.headers["referrer-policy"], "no-referrer")
        self.assertEqual(root_health_response.headers["content-security-policy"], CONTENT_SECURITY_POLICY)
        self.assertEqual(health_response.headers["x-content-type-options"], "nosniff")
        self.assertEqual(health_response.headers["referrer-policy"], "no-referrer")
        self.assertEqual(health_response.headers["content-security-policy"], CONTENT_SECURITY_POLICY)
        self.assertEqual(health["capabilities"]["streaming"], "available")
        self.assertEqual(health["capabilities"]["queue_control"], "available")
        self.assertEqual(health["capabilities"]["checkpoints"], "degraded")
        self.assertEqual(health["capabilities"]["branching"], "degraded")
        self.assertEqual(health["capabilities"]["time_travel"], "degraded")
        self.assertEqual(health["capabilities"]["generated_ui"], "degraded")
        self.assertEqual(state["data"]["history"]["branches"][0]["id"], "branch_main")
        self.assertEqual(activity["data"]["activity"]["private_threads"][0]["thread_id"], "thread:mention:agent")
        self.assertEqual(message["data"]["event"]["content"], "@agent hello")
        self.assertFalse(runtime["data"]["runtime"]["mention_hook_enabled"])
        self.assertEqual(stopped["data"]["team_id"], "team")
        self.assertEqual(runs["data"][0]["id"], "run_01")
        self.assertEqual(joined["data"]["stream_url"], "/api/studio/v1/stream?run_id=run_01")
        self.assertEqual(missing_run_join["errors"][0]["field"], "run_id")
        self.assertEqual(queue["data"], [])
        self.assertEqual(checkpoints["data"], [])
        self.assertEqual(checkpoint["errors"][0]["code"], "not_found")
        self.assertEqual(branches["data"][0]["id"], "branch_main")
        self.assertEqual(switched["data"][0]["id"], "branch_main")
        self.assertEqual(interrupts["data"], [])
        self.assertEqual(missing_file["errors"][0]["field"], "file_id")
        self.assertEqual(missing_queue["errors"][0]["code"], "not_found")
        stream_events = [frame.event for frame in buffer.replay_after(None) or []]
        self.assertIn("conversation.event.appended", stream_events)
        self.assertIn("run.started", stream_events)
        self.assertIn("run.completed", stream_events)
        self.assertLess(stream_events.index("run.started"), stream_events.index("conversation.delivery.updated"))
        self.assertLess(stream_events.index("conversation.delivery.updated"), stream_events.index("run.completed"))
        started_frame = [frame for frame in buffer.replay_after(None) or [] if frame.event == "run.started"][0]
        updated_frame = [frame for frame in buffer.replay_after(None) or [] if frame.event == "run.updated"][0]
        self.assertEqual(started_frame.payload["status"], "running")
        self.assertEqual(started_frame.payload["id"], "run_01")
        self.assertEqual(updated_frame.payload["id"], "run_01")
        self.assertTrue(updated_frame.payload["metadata"]["stop_requested"])
        self.assertEqual(fake.runtime_calls, [("hook", False), ("cascade", None)])
        self.assertEqual(fake.stopped, ["agent"])

    def test_stop_agent_without_active_run_publishes_only_agent_state(self) -> None:
        fake = self._fake_conversation(running=False)
        buffer = StreamBuffer()
        client = TestClient(create_app(fake, stream_buffer=buffer))

        stopped = client.post("/api/studio/v1/agents/agent/stop").json()

        stream_events = [frame.event for frame in buffer.replay_after(None) or []]
        self.assertEqual(stopped["data"]["team_id"], "team")
        self.assertEqual(fake.stopped, ["agent"])
        self.assertIn("agent.state.updated", stream_events)
        self.assertNotIn("run.updated", stream_events)

    def test_state_includes_per_participant_private_activity(self) -> None:
        fake = self._fake_conversation(participants=["agent-a", "", "agent-b"], running=False)
        client = TestClient(create_app(fake))

        state = client.get("/api/studio/v1/state").json()
        activity = client.get("/api/studio/v1/activity?agent_id=agent-a").json()
        encoded_activity = client.get("/api/studio/v1/activity?agent_id=agent%20a").json()

        self.assertEqual(
            [thread["thread_id"] for thread in state["data"]["activity"]["private_threads"]],
            ["thread:mention:agent-a", "thread:mention:agent-b"],
        )
        self.assertEqual(
            [thread["messages"][0]["name"] for thread in state["data"]["activity"]["private_threads"]],
            ["agent-a", "agent-b"],
        )
        self.assertEqual(
            [thread["thread_id"] for thread in activity["data"]["activity"]["private_threads"]],
            ["thread:mention:agent-a"],
        )
        self.assertEqual(
            encoded_activity["data"]["activity"]["private_threads"][0]["thread_id"],
            "thread:mention:agent a",
        )

    def test_queue_controls_cancel_and_clear_pending_entries(self) -> None:
        cancel_fake = self._fake_conversation(running=False, queued=True, queued_after_seq=1)
        buffer = StreamBuffer()
        client = TestClient(create_app(cancel_fake, stream_buffer=buffer))

        queue = client.get("/api/studio/v1/queue").json()
        cancelled = client.delete(f"/api/studio/v1/queue/{queue['data'][0]['id']}").json()

        self.assertTrue(queue["data"][0]["can_cancel"])
        self.assertEqual(cancelled["data"], [])
        self.assertEqual(cancel_fake.cancelled, ["agent"])
        self.assertIn("queue.updated", [frame.event for frame in buffer.replay_after(None) or []])

        clear_fake = self._fake_conversation(running=False, queued=True, queued_after_seq=1)
        client = TestClient(create_app(clear_fake))
        cleared = client.post("/api/studio/v1/queue/clear", json={"scope": "pending"}).json()

        self.assertEqual(cleared["data"], [])
        self.assertEqual(clear_fake.cleared, ["pending"])

        running_fake = self._fake_conversation(running=True, queued=True, queued_after_seq=1)
        client = TestClient(create_app(running_fake))
        running_queue = client.get("/api/studio/v1/queue").json()
        unsupported = client.delete(f"/api/studio/v1/queue/{running_queue['data'][0]['id']}").json()

        self.assertFalse(running_queue["data"][0]["can_cancel"])
        self.assertEqual(unsupported["errors"][0]["details"]["capability"], "queue_control")

    def test_queue_includes_and_clears_failed_delivery_entries(self) -> None:
        failed_delivery = {
            "id": "delivery_failed",
            "team_id": "team",
            "conversation_id": "thread",
            "agent_id": "agent",
            "run_id": "run_failed",
            "snapshot_seq": 1,
            "status": "failed",
            "created_at": "2026-06-01T10:00:02Z",
            "completed_at": "2026-06-01T10:00:03Z",
            "error": "boom",
        }
        fake = self._fake_conversation(running=False, deliveries=[failed_delivery])
        buffer = StreamBuffer()
        client = TestClient(create_app(fake, stream_buffer=buffer))

        queue = client.get("/api/studio/v1/queue").json()
        cleared = client.post("/api/studio/v1/queue/clear", json={"scope": "failed"}).json()
        state_after_clear = client.get("/api/studio/v1/state").json()

        self.assertEqual(queue["data"][0]["id"], "queue_failed_delivery_failed")
        self.assertEqual(queue["data"][0]["status"], "failed")
        self.assertEqual(queue["data"][0]["message_event_id"], "event_01")
        self.assertEqual(queue["data"][0]["error"], "boom")
        self.assertFalse(queue["data"][0]["can_cancel"])
        self.assertEqual(cleared["data"], [])
        self.assertEqual(state_after_clear["data"]["queue"], [])
        self.assertEqual(state_after_clear["data"]["conversation"]["deliveries"][0]["id"], "delivery_failed")
        self.assertEqual(fake.cleared, ["failed"])
        self.assertIn("queue.updated", [frame.event for frame in buffer.replay_after(None) or []])

    def test_message_append_accepts_attachment_uploads_and_rejects_invalid_content(self) -> None:
        fake = self._fake_conversation()
        client = TestClient(create_app(fake))

        uploaded = client.post(
            "/api/studio/v1/messages",
            json={
                "content": "@agent see attachment",
                "author_id": "human",
                "attachments": [
                    {
                        "filename": "notes.txt",
                        "content_base64": base64.b64encode(b"hello").decode("ascii"),
                        "media_type": "text/plain",
                    }
                ],
            },
        ).json()
        invalid = client.post(
            "/api/studio/v1/messages",
            json={
                "content": "@agent bad attachment",
                "author_id": "human",
                "attachments": [{"filename": "bad.txt", "content_base64": "not base64!"}],
            },
        ).json()

        self.assertEqual(uploaded["data"]["event"]["content"], "@agent see attachment")
        self.assertEqual(fake.messages[0][2][0].filename, "notes.txt")
        self.assertEqual(fake.messages[0][2][0].size_bytes, 5)
        self.assertEqual(invalid["errors"][0]["code"], "invalid_request")
        self.assertIn("base64", invalid["errors"][0]["message"])

    def test_message_append_is_idempotent_by_client_message_id(self) -> None:
        fake = self._fake_conversation()
        client = TestClient(create_app(fake))

        first = client.post(
            "/api/studio/v1/messages",
            json={
                "content": "@agent recoverable",
                "author_id": "human",
                "client_message_id": "client_01",
            },
        ).json()
        second = client.post(
            "/api/studio/v1/messages",
            json={
                "content": "@agent recoverable",
                "author_id": "human",
                "client_message_id": "client_01",
            },
        ).json()

        self.assertEqual(len(fake.messages), 1)
        self.assertEqual(first["data"]["event"]["id"], second["data"]["event"]["id"])
        self.assertEqual(second["data"]["event"]["metadata"]["client_message_id"], "client_01")
        self.assertEqual(second["data"]["deliveries"], [])

    def test_session_thread_files_changes_and_terminal_contracts(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root_dir = Path(temp_dir)
            files_dir = root_dir / ".coding-agents" / "conversations" / "thread" / "files"
            files_dir.mkdir(parents=True)
            (files_dir / "file_01").write_bytes(b"hello")
            (files_dir / "file_html").write_bytes(b"<h1>x</h1>")
            attachments = [
                {
                    "id": "file_01",
                    "filename": "notes.txt",
                    "uri": "conversation://files/file_01",
                    "media_type": "text/plain",
                    "size_bytes": 5,
                    "added_by": "human",
                },
                {
                    "id": "file_html",
                    "filename": "page.html",
                    "uri": "conversation://files/file_html",
                    "media_type": "text/html",
                    "size_bytes": 8,
                    "added_by": "human",
                },
            ]
            client = TestClient(create_app(self._fake_conversation(attachments=attachments, root_dir=root_dir)))

            session = client.get("/api/studio/v1/session").json()
            conversations = client.get("/api/studio/v1/conversations?limit=10").json()
            files = client.get("/api/studio/v1/files").json()
            preview = client.get("/api/studio/v1/files/file_01/preview")
            download = client.get("/api/studio/v1/files/file_html/download")
            changes = client.get("/api/studio/v1/changes").json()
            terminal = client.post("/api/studio/v1/terminal/sessions").json()
            terminal_output = client.get(
                f"/api/studio/v1/terminal/sessions/{terminal['data']['session_id']}/output"
            ).json()
            resized_terminal = client.post(
                f"/api/studio/v1/terminal/sessions/{terminal['data']['session_id']}/resize",
                json={"columns": 120, "rows": 40},
            ).json()
            stopped_terminal = client.delete(
                f"/api/studio/v1/terminal/sessions/{terminal['data']['session_id']}"
            ).json()

            self.assertEqual(session["data"]["team_id"], "team")
            self.assertEqual(session["data"]["conversation_id"], "thread")
            self.assertEqual(session["data"]["resolved_root_dir"], str(root_dir.resolve()))
            self.assertEqual(session["data"]["checkpointer"]["backend"], "memory")
            self.assertEqual(conversations["data"]["current_conversation_id"], "thread")
            self.assertEqual(conversations["data"]["conversations"][0]["conversation_id"], "thread")
            self.assertEqual(files["data"]["files"][0]["preview_url"], "/api/studio/v1/files/file_01/preview")
            self.assertEqual(files["data"]["files"][0]["download_url"], "/api/studio/v1/files/file_01/download")
            self.assertIsNone(files["data"]["files"][1]["preview_url"])
            self.assertEqual(preview.content, b"hello")
            self.assertEqual(download.content, b"<h1>x</h1>")
            self.assertEqual(changes["data"], {"changes": [], "supported": False})
            self.assertEqual(terminal["data"]["cwd"], str(root_dir.resolve()))
            self.assertEqual(terminal["data"]["status"], "running")
            self.assertIn("Terminal started", terminal_output["data"]["chunks"][0]["text"])
            self.assertEqual(resized_terminal["data"]["columns"], 120)
            self.assertEqual(resized_terminal["data"]["rows"], 40)
            self.assertEqual(stopped_terminal["data"]["status"], "terminated")

    def test_changes_contract_reports_git_status_and_diffs(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root_dir = Path(temp_dir)
            subprocess.run(["git", "-C", str(root_dir), "init"], check=True, capture_output=True)
            subprocess.run(["git", "-C", str(root_dir), "config", "user.email", "test@example.com"], check=True)
            subprocess.run(["git", "-C", str(root_dir), "config", "user.name", "Test"], check=True)
            tracked = root_dir / "tracked.txt"
            tracked.write_text("before\n", encoding="utf-8")
            subprocess.run(["git", "-C", str(root_dir), "add", "tracked.txt"], check=True)
            subprocess.run(["git", "-C", str(root_dir), "commit", "-m", "seed"], check=True, capture_output=True)
            tracked.write_text("after\n", encoding="utf-8")
            (root_dir / "created.txt").write_text("new file\n", encoding="utf-8")
            client = TestClient(create_app(self._fake_conversation(root_dir=root_dir)))

            changes = client.get("/api/studio/v1/changes").json()
            by_path = {change["path"]: change for change in changes["data"]["changes"]}
            diff = client.get(by_path["tracked.txt"]["diff_url"]).json()
            untracked_diff = client.get(by_path["created.txt"]["diff_url"]).json()

            self.assertTrue(changes["data"]["supported"])
            self.assertEqual(by_path["tracked.txt"]["status"], "modified")
            self.assertEqual(by_path["created.txt"]["status"], "untracked")
            self.assertIn("-before", diff["data"]["diff"])
            self.assertIn("+after", diff["data"]["diff"])
            self.assertIn("+new file", untracked_diff["data"]["diff"])

    def test_studio_attachment_factory_enforces_file_and_request_limits(self) -> None:
        fake = self._fake_conversation()
        factory = StudioAttachmentRefFactory(fake)
        nine_mib = base64.b64encode(b"x" * (9 * 1024 * 1024)).decode("ascii")
        oversized = base64.b64encode(b"x" * (MAX_ATTACHMENT_BYTES + 1)).decode("ascii")

        passthrough = factory.refs([{"id": "existing_file"}], author_id="human")

        with self.assertRaisesRegex(ValueError, "10 MiB"):
            factory.refs([{"filename": "large.bin", "content_base64": oversized}], author_id="human")
        with self.assertRaisesRegex(ValueError, "25 MiB"):
            factory.refs(
                [
                    {"filename": "one.bin", "content_base64": nine_mib},
                    {"filename": "two.bin", "content_base64": nine_mib},
                    {"filename": "three.bin", "content_base64": nine_mib},
                ],
                author_id="human",
            )

        self.assertEqual(passthrough, [{"id": "existing_file"}])

    def test_interrupts_list_and_resume_use_runtime_records(self) -> None:
        fake = self._fake_conversation(interrupts=True)
        buffer = StreamBuffer()
        client = TestClient(create_app(fake, stream_buffer=buffer))

        state = client.get("/api/studio/v1/state").json()
        pending = client.get("/api/studio/v1/interrupts").json()
        resumed = client.post(
            "/api/studio/v1/interrupts/interrupt_01/resume",
            json={"decision": "respond", "response": "approved with notes"},
        ).json()
        missing = client.post("/api/studio/v1/interrupts/missing/resume", json={"decision": "approve"}).json()

        self.assertEqual(pending["capabilities"]["interrupts"], "degraded")
        self.assertEqual(state["data"]["interrupts"][0]["status"], "pending")
        self.assertEqual(pending["data"][0]["payload"]["action"], "write_file")
        self.assertEqual(resumed["data"]["interrupts"], [])
        self.assertEqual(fake.runtime.list_interrupts(active_only=False)[0].decisions[0]["response"], "approved with notes")
        self.assertEqual(missing["errors"][0]["field"], "interrupt_id")
        self.assertIn("interrupt.resolved", [frame.event for frame in buffer.replay_after(None) or []])

    def test_checkpoint_history_reads_langgraph_sqlite_rows(self) -> None:
        with sqlite3.connect(":memory:", check_same_thread=False) as connection:
            self._create_checkpoint_tables(connection)
            serde = JsonPlusSerializer()
            checkpoint_type, checkpoint_blob = serde.dumps_typed(
                {
                    "id": "checkpoint_01",
                    "ts": "2026-06-01T10:00:02+00:00",
                    "channel_values": {
                        "messages": [
                            {
                                "role": "assistant",
                                "content": "answer",
                                "tool_calls": [{"id": "call_01"}],
                                "response_metadata": {
                                    "conversation_event_id": "event_01",
                                    "conversation_seq": 1,
                                },
                            }
                        ]
                    },
                }
            )
            write_type, write_blob = serde.dumps_typed(AIMessage(content="write summary"))
            connection.execute(
                """
                insert into checkpoints (thread_id, checkpoint_ns, checkpoint_id, parent_checkpoint_id, type, checkpoint, metadata)
                values (?, '', 'checkpoint_01', null, ?, ?, ?)
                """,
                (
                    "thread:mention:agent",
                    checkpoint_type,
                    checkpoint_blob,
                    json.dumps({"step": 1, "target_agent_id": "agent"}).encode("utf-8"),
                ),
            )
            connection.execute(
                """
                insert into checkpoints (thread_id, checkpoint_ns, checkpoint_id, parent_checkpoint_id, type, checkpoint, metadata)
                values (?, '', 'checkpoint_02', 'checkpoint_01', null, null, null)
                """,
                ("thread:mention:agent",),
            )
            connection.execute(
                """
                insert into writes (thread_id, checkpoint_ns, checkpoint_id, task_id, idx, channel, type, value)
                values (?, '', 'checkpoint_02', 'task', 0, 'messages', ?, ?)
                """,
                ("thread:mention:agent", write_type, write_blob),
            )
            connection.commit()
            fake = self._fake_conversation(connection=connection)
            client = TestClient(create_app(fake))

            state = client.get("/api/studio/v1/state").json()
            checkpoints = client.get("/api/studio/v1/checkpoints").json()
            checkpoint = client.get("/api/studio/v1/checkpoints/checkpoint_02").json()
            resumed = client.post("/api/studio/v1/checkpoints/checkpoint_02/resume", json={"mode": "resume"}).json()
            branches = client.get("/api/studio/v1/branches").json()
            empty_participant_history = CheckpointHistoryReader().checkpoints(
                self._fake_conversation(connection=connection, participants=[]),
                {**fake.state(), "participants": []},
            )

            self.assertEqual(state["data"]["history"]["checkpoints"][0]["created_at"], "2026-06-01T10:00:02Z")
            self.assertEqual(checkpoints["capabilities"]["checkpoints"], "available")
            self.assertEqual(checkpoints["data"][0]["summary"]["tool_call_count"], 1)
            self.assertEqual(checkpoints["data"][0]["summary"]["event_id"], "event_01")
            self.assertEqual(checkpoints["data"][0]["summary"]["event_seq"], 1)
            self.assertEqual(checkpoints["data"][1]["summary"]["message_count"], 1)
            self.assertEqual(checkpoint["data"]["parent_checkpoint_id"], "checkpoint_01")
            self.assertEqual(resumed["errors"][0]["details"]["capability"], "time_travel")
            self.assertEqual(branches["data"][0]["head_checkpoint_id"], "checkpoint_02")
            self.assertEqual(empty_participant_history, [])

        with sqlite3.connect(":memory:", check_same_thread=False) as empty_connection:
            empty_client = TestClient(create_app(self._fake_conversation(connection=empty_connection)))
            empty_state = empty_client.get("/api/studio/v1/state")
            empty_checkpoints = empty_client.get("/api/studio/v1/checkpoints")

            self.assertEqual(empty_state.status_code, 200)
            self.assertEqual(empty_state.json()["data"]["history"]["checkpoints"], [])
            self.assertEqual(empty_checkpoints.json()["data"], [])

    def test_branch_creation_and_switching_use_runtime_metadata(self) -> None:
        with sqlite3.connect(":memory:", check_same_thread=False) as connection:
            self._create_checkpoint_tables(connection)
            checkpoint_type, checkpoint_blob = JsonPlusSerializer().dumps_typed(
                {
                    "ts": "2026-06-01T10:00:02+00:00",
                    "channel_values": {
                        "messages": [
                            AIMessage(
                                content="checkpoint reply",
                                response_metadata={"conversation_event_id": "event_01", "conversation_seq": 1},
                            )
                        ]
                    },
                }
            )
            connection.execute(
                """
                insert into checkpoints (thread_id, checkpoint_ns, checkpoint_id, parent_checkpoint_id, type, checkpoint, metadata)
                values ('thread:mention:agent', '', 'checkpoint_01', null, ?, ?, null)
                """,
                (checkpoint_type, checkpoint_blob),
            )
            connection.commit()
            fake = self._fake_conversation(connection=connection, branching=True)
            buffer = StreamBuffer()
            client = TestClient(create_app(fake, stream_buffer=buffer))

            created = client.post(
                "/api/studio/v1/branches",
                json={"label": "Alternative", "checkpoint_id": "checkpoint_01"},
            ).json()
            current_created = client.post("/api/studio/v1/branches", json={"label": "Current"}).json()
            message_created = client.post("/api/studio/v1/branches", json={"label": "Message", "message_id": "event_01"}).json()
            missing_message = client.post(
                "/api/studio/v1/branches",
                json={"label": "Missing message", "message_id": "event_missing"},
            ).json()
            missing_checkpoint = client.post(
                "/api/studio/v1/branches",
                json={"label": "Missing", "checkpoint_id": "missing"},
            ).json()
            missing_branch = client.post("/api/studio/v1/branches/branch_missing/switch").json()
            switched = client.post(f"/api/studio/v1/branches/{created['data']['id']}/switch").json()
            state = client.get("/api/studio/v1/state").json()
            checkpoints = client.get("/api/studio/v1/checkpoints").json()

            self.assertEqual(created["capabilities"]["branching"], "available")
            self.assertEqual(created["capabilities"]["time_travel"], "available")
            self.assertEqual(checkpoints["data"][0]["capabilities"]["branch_from_here"], "available")
            self.assertEqual(checkpoints["data"][0]["capabilities"]["resume"], "available")
            self.assertEqual(created["data"]["label"], "Alternative")
            self.assertEqual(created["data"]["parent_branch_id"], "branch_main")
            self.assertEqual(created["data"]["origin_checkpoint_id"], "checkpoint_01")
            self.assertFalse(created["data"]["current"])
            self.assertEqual(current_created["data"]["origin_checkpoint_id"], "checkpoint_01")
            self.assertEqual(message_created["data"]["origin_checkpoint_id"], "checkpoint_01")
            self.assertEqual(missing_message["errors"][0]["field"], "message_id")
            self.assertEqual(missing_checkpoint["errors"][0]["code"], "not_found")
            self.assertEqual(missing_branch["errors"][0]["field"], "branch_id")
            self.assertEqual(state["data"]["history"]["current_branch_id"], created["data"]["id"])
            self.assertTrue([item for item in switched["data"] if item["id"] == created["data"]["id"]][0]["current"])
            self.assertIn("branch.updated", [frame.event for frame in buffer.replay_after(None) or []])

            resumed = client.post("/api/studio/v1/checkpoints/checkpoint_01/resume", json={"mode": "resume"}).json()
            branch_events = [
                event
                for event in resumed["data"]["conversation"]["events"]
                if event["metadata"].get("time_travel_mode") == "resume"
            ]

            self.assertEqual(resumed["data"]["history"]["current_branch_id"], branch_events[0]["metadata"]["branch_id"])
            self.assertEqual(branch_events[0]["content"], "checkpoint replay")

            edited = client.post(
                "/api/studio/v1/checkpoints/checkpoint_01/resume",
                json={"mode": "edit", "edited_content": "edited checkpoint reply"},
            ).json()
            regenerated = client.post(
                "/api/studio/v1/checkpoints/checkpoint_01/resume",
                json={"mode": "regenerate"},
            ).json()
            edited_events = [
                event
                for event in edited["data"]["conversation"]["events"]
                if event["metadata"].get("time_travel_mode") == "edit"
            ]
            regenerated_events = [
                event
                for event in regenerated["data"]["conversation"]["events"]
                if event["metadata"].get("time_travel_mode") == "regenerate"
            ]

            self.assertEqual(edited_events[0]["content"], "edited checkpoint reply")
            self.assertEqual(regenerated_events[0]["content"], "checkpoint replay")
            self.assertEqual(
                regenerated["data"]["history"]["current_branch_id"],
                regenerated_events[0]["metadata"]["branch_id"],
            )

        empty_fake = self._fake_conversation(branching=True)
        empty_client = TestClient(create_app(empty_fake))
        unsupported = empty_client.post("/api/studio/v1/branches", json={"label": "No checkpoint"}).json()

        self.assertEqual(unsupported["errors"][0]["details"]["capability"], "branching")

        with sqlite3.connect(":memory:", check_same_thread=False) as unmatched_connection:
            self._create_checkpoint_tables(unmatched_connection)
            unmatched_connection.execute(
                """
                insert into checkpoints (thread_id, checkpoint_ns, checkpoint_id, parent_checkpoint_id, type, checkpoint, metadata)
                values ('thread:mention:agent', '', 'checkpoint_01', null, null, null, null)
                """
            )
            unmatched_connection.commit()
            unmatched_client = TestClient(create_app(self._fake_conversation(connection=unmatched_connection, branching=True)))
            unsupported_message = unmatched_client.post(
                "/api/studio/v1/branches",
                json={"label": "Unmatched message", "message_id": "event_01"},
            ).json()

            self.assertEqual(unsupported_message["errors"][0]["details"]["capability"], "branching")

    def test_message_edit_creates_branch_and_versioned_human_event(self) -> None:
        fake = self._fake_conversation(branching=True)
        buffer = StreamBuffer()
        client = TestClient(create_app(fake, stream_buffer=buffer))

        edited = client.post(
            "/api/studio/v1/messages/event_01/edit",
            json={"content": "@agent edited", "author_id": "human"},
        ).json()
        missing = client.post(
            "/api/studio/v1/messages/event_missing/edit",
            json={"content": "@agent edited", "author_id": "human"},
        ).json()

        current_branch_id = edited["data"]["history"]["current_branch_id"]
        events = edited["data"]["conversation"]["events"]

        self.assertNotEqual(current_branch_id, "branch_main")
        self.assertEqual(events[0]["content"], "@agent edited")
        self.assertEqual(events[0]["branch_id"], current_branch_id)
        self.assertEqual(events[0]["logical_message_id"], "event_01")
        self.assertEqual(events[0]["version_parent_event_id"], "event_01")
        self.assertEqual(missing["errors"][0]["field"], "message_id")
        stream_events = [frame.event for frame in buffer.replay_after(None) or []]
        self.assertIn("conversation.event.appended", stream_events)
        self.assertIn("branch.updated", stream_events)

    def test_file_download_serves_public_attachments_with_content_checks(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root_dir = Path(temp_dir)
            files_dir = root_dir / ".coding-agents" / "conversations" / "thread" / "files"
            files_dir.mkdir(parents=True)
            (files_dir / "file_01").write_bytes(b"hello")
            (files_dir / "file_plain").write_bytes(b"plain")
            attachments = [
                {
                    "id": "file_01",
                    "filename": "notes.txt",
                    "uri": "conversation://files/file_01",
                    "media_type": "text/plain",
                    "size_bytes": 5,
                    "added_by": "human",
                },
                {
                    "id": "file_html",
                    "filename": "page.html",
                    "uri": "conversation://files/file_html",
                    "media_type": "text/html",
                    "size_bytes": 12,
                    "added_by": "human",
                },
                {
                    "id": "file_missing",
                    "filename": "missing.txt",
                    "uri": "conversation://files/file_missing",
                    "media_type": "text/plain",
                    "size_bytes": 7,
                    "added_by": "human",
                },
                {
                    "id": "file_plain",
                    "filename": "plain.bin",
                    "uri": "conversation://files/file_plain",
                    "media_type": None,
                    "size_bytes": 5,
                    "added_by": "human",
                },
            ]
            client = TestClient(create_app(self._fake_conversation(attachments=attachments, root_dir=root_dir)))

            downloaded = client.get("/api/studio/v1/files/file_01")
            plain = client.get("/api/studio/v1/files/file_plain")
            blocked = client.get("/api/studio/v1/files/file_html").json()
            missing = client.get("/api/studio/v1/files/file_missing").json()

            self.assertEqual(downloaded.content, b"hello")
            self.assertIn("text/plain", downloaded.headers["content-type"])
            self.assertEqual(downloaded.headers["x-content-type-options"], "nosniff")
            self.assertEqual(downloaded.headers["referrer-policy"], "no-referrer")
            self.assertEqual(plain.content, b"plain")
            self.assertEqual(blocked["errors"][0]["code"], "unsupported_media_type")
            self.assertEqual(missing["errors"][0]["code"], "not_found")

        no_root = TestClient(create_app(self._fake_conversation(attachments=[attachments[0]])))
        no_root_response = no_root.get("/api/studio/v1/files/file_01").json()

        self.assertEqual(no_root_response["errors"][0]["field"], "file_id")

    def test_compatibility_endpoints_keep_legacy_shapes(self) -> None:
        fake = self._fake_conversation()
        client = TestClient(create_app(fake))

        state = client.get("/api/state").json()
        activity = client.get("/api/activity?agent_id=agent").json()
        message = client.post("/api/messages", json={"content": "@agent legacy"}).json()
        runtime = client.post("/api/runtime", json={"mention_hook_enabled": False, "max_cascade_turns": ""}).json()
        stopped = client.post("/api/stop", json={"agent_id": "agent"}).json()

        self.assertEqual(state["team_id"], "team")
        self.assertEqual(activity["private_thread_id"], "thread:mention:agent")
        self.assertNotIn("schema_version", message)
        self.assertEqual(message["event"]["content"], "@agent legacy")
        self.assertEqual(runtime["runtime"]["max_cascade_turns"], None)
        self.assertEqual(stopped["team_id"], "team")

    def test_route_table_covers_contract_slice(self) -> None:
        client = TestClient(create_app(self._fake_conversation()))
        paths = set(client.app.openapi()["paths"])

        for path in {
            "/api/studio/v1/health",
            "/api/studio/v1/state",
            "/api/studio/v1/activity",
            "/api/studio/v1/messages",
            "/api/studio/v1/messages/{message_id}/edit",
            "/api/studio/v1/runtime",
            "/api/studio/v1/agents/{agent_id}/stop",
            "/api/studio/v1/stream",
            "/api/studio/v1/runs",
            "/api/studio/v1/runs/{run_id}/join",
            "/api/studio/v1/queue",
            "/api/studio/v1/queue/{queue_item_id}",
            "/api/studio/v1/queue/clear",
            "/api/studio/v1/checkpoints",
            "/api/studio/v1/checkpoints/{checkpoint_id}",
            "/api/studio/v1/checkpoints/{checkpoint_id}/resume",
            "/api/studio/v1/branches",
            "/api/studio/v1/branches/{branch_id}/switch",
            "/api/studio/v1/interrupts",
            "/api/studio/v1/interrupts/{interrupt_id}/resume",
            "/api/studio/v1/session",
            "/api/studio/v1/session/conversation",
            "/api/studio/v1/conversations",
            "/api/studio/v1/files",
            "/api/studio/v1/files/{file_id}/preview",
            "/api/studio/v1/files/{file_id}/download",
            "/api/studio/v1/files/{file_id}",
            "/api/studio/v1/changes",
            "/api/studio/v1/changes/{change_id}/diff",
            "/api/studio/v1/terminal/sessions",
            "/api/studio/v1/terminal/sessions/{session_id}/output",
            "/api/studio/v1/terminal/sessions/{session_id}/input",
            "/api/studio/v1/terminal/sessions/{session_id}/resize",
            "/api/studio/v1/terminal/sessions/{session_id}",
        }:
            self.assertIn(path, paths)

    def test_unsupported_mutations_and_validation_errors_use_standard_envelope(self) -> None:
        client = TestClient(create_app(self._fake_conversation()))

        resume_checkpoint = client.post("/api/studio/v1/checkpoints/checkpoint_01/resume", json={"mode": "edit"}).json()
        create_branch = client.post("/api/studio/v1/branches", json={"label": "Alternative"}).json()
        edit_message = client.post("/api/studio/v1/messages/event_01/edit", json={"content": "edited"}).json()
        switch_branch = client.post("/api/studio/v1/branches/branch_alt/switch").json()
        resume_interrupt = client.post("/api/studio/v1/interrupts/interrupt_01/resume", json={"decision": "approve"}).json()
        invalid_request = client.post("/api/studio/v1/messages", json={"author_id": "human"}).json()

        self.assertEqual(resume_checkpoint["errors"][0]["code"], "not_found")
        self.assertEqual(create_branch["errors"][0]["details"]["capability"], "branching")
        self.assertEqual(edit_message["errors"][0]["details"]["capability"], "branching")
        self.assertEqual(switch_branch["errors"][0]["details"]["capability"], "branching")
        self.assertEqual(resume_interrupt["errors"][0]["details"]["capability"], "interrupts")
        self.assertEqual(invalid_request["errors"][0]["code"], "invalid_request")

    def test_custom_exception_handlers_return_envelopes(self) -> None:
        app = create_app(self._fake_conversation())

        @app.get("/raises-value-error")
        async def raises_value_error():
            raise ValueError("bad value")

        @app.get("/raises-validation-error")
        async def raises_validation_error():
            RuntimeUpdateRequest.model_validate({"max_cascade_turns": "bad"})

        client = TestClient(app)

        value_error = client.get("/raises-value-error").json()
        validation_error = client.get("/raises-validation-error").json()

        self.assertEqual(value_error["errors"][0]["message"], "bad value")
        self.assertEqual(validation_error["errors"][0]["code"], "invalid_request")

    def test_stream_buffer_replays_recent_frames_and_detects_gaps(self) -> None:
        buffer = StreamBuffer(max_frames=2)
        first = buffer.publish("studio.hello", {})
        second = buffer.publish("snapshot.replace", {"ok": True})
        third = buffer.publish("studio.heartbeat", {})

        self.assertEqual([frame.id for frame in buffer.replay_after(second.cursor) or []], [third.id])
        self.assertEqual([frame.id for frame in buffer.replay_after(second.id) or []], [third.id])
        self.assertIsNone(buffer.replay_after(first.cursor))
        self.assertIsNone(buffer.replay_after("bad-cursor"))
        self.assertIsNone(buffer.replay_after("stream_not-a-number"))
        self.assertIsNone(buffer.replay_after("event_seq:not-an-int"))
        self.assertEqual(buffer.latest_cursor(), third.cursor)

    def test_stream_client_queue_drops_slow_clients_after_bounded_queue_fills(self) -> None:
        async def run() -> None:
            queue = StreamClientQueue(max_items=1, put_timeout_seconds=0)

            self.assertTrue(await queue.put("first"))
            self.assertFalse(await queue.put("second"))
            self.assertTrue(queue.closed)
            queue.close()
            self.assertIsNone(await queue.get())

        asyncio.run(run())

    def test_stream_client_queue_allows_waiting_send_when_consumer_drains(self) -> None:
        async def run() -> None:
            queue = StreamClientQueue(max_items=1, put_timeout_seconds=1)

            self.assertTrue(await queue.put("first"))

            async def drain() -> str | None:
                await asyncio.sleep(0)
                return await queue.get()

            drain_task = asyncio.create_task(drain())

            self.assertTrue(await queue.put("second"))
            self.assertEqual(await drain_task, "first")
            self.assertEqual(await queue.get(), "second")

        asyncio.run(run())

    def test_stream_event_generator_closes_when_request_is_disconnected(self) -> None:
        controller = StudioApiController(self._fake_conversation(), stream_buffer=StreamBuffer(max_frames=6))

        async def collect() -> list[str]:
            async def is_disconnected():
                return True

            request = SimpleNamespace(is_disconnected=is_disconnected, headers={})
            frames = []
            async for frame in _stream_events(controller, request, cursor=None, run_id=None, agent_id=None):
                frames.append(frame)
            return frames

        frames = asyncio.run(collect())

        self.assertIn("event: studio.hello", frames[0])
        self.assertIn("event: snapshot.replace", frames[1])

    def test_stream_producer_stops_when_client_queue_rejects_frames(self) -> None:
        async def run() -> None:
            cases = [
                (1, None, None, None),
                (2, None, None, None),
                (2, "event_seq:0", None, None),
                (2, "event_seq:1", "queue.updated", {"items": []}),
            ]
            for reject_on, cursor, replay_event, replay_payload in cases:
                controller = StudioApiController(self._fake_conversation(), stream_buffer=StreamBuffer(max_frames=8))
                if cursor is not None and replay_event is None:
                    controller.stream_buffer.publish("old", {})
                if replay_event is not None:
                    retained_cursor = controller.stream_buffer.publish("old", {}).cursor
                    controller.stream_buffer.publish(replay_event, replay_payload)
                    cursor = retained_cursor
                queue = _RejectingStreamQueue(reject_on)

                async def is_disconnected():
                    return True

                request = SimpleNamespace(is_disconnected=is_disconnected, headers={})

                await _produce_stream_events(controller, request, cursor=cursor, run_id=None, agent_id=None, client_queue=queue)

                self.assertTrue(queue.closed)

        asyncio.run(run())

    def test_stream_producer_stops_when_snapshot_diff_queue_rejects_frames(self) -> None:
        async def run(reject_on: int) -> _RejectingStreamQueue:
            controller = StudioApiController(self._fake_conversation(), stream_buffer=StreamBuffer(max_frames=12))
            initial_snapshot = controller.state().model_dump(mode="json")
            initial_snapshot["activity"]["private_threads"] = []
            changed_snapshot = json.loads(json.dumps(initial_snapshot))
            changed_snapshot["activity"]["private_threads"] = [
                {
                    "agent_id": "agent",
                    "thread_id": "thread:mention:agent",
                    "messages": [{"type": "ai", "name": "agent", "content": "working", "tool_calls": []}],
                }
            ]
            snapshots = [initial_snapshot, changed_snapshot]
            calls = {"state": 0, "disconnect": 0}

            def state():
                index = min(calls["state"], len(snapshots) - 1)
                calls["state"] += 1
                snapshot = json.loads(json.dumps(snapshots[index]))
                return SimpleNamespace(model_dump=lambda mode="json": snapshot)

            async def is_disconnected():
                calls["disconnect"] += 1
                return calls["disconnect"] > 1

            async def sleep(_seconds):
                return None

            controller.state = state
            request = SimpleNamespace(is_disconnected=is_disconnected, headers={})
            queue = _RejectingStreamQueue(reject_on)
            with patch("src.webapp_studio.backend.server.asyncio.sleep", sleep):
                await _produce_stream_events(controller, request, cursor=None, run_id=None, agent_id=None, client_queue=queue)
            return queue

        diff_rejected = asyncio.run(run(3))
        snapshot_rejected = asyncio.run(run(4))

        self.assertTrue(diff_rejected.closed)
        self.assertTrue(snapshot_rejected.closed)

    def test_stream_event_generator_covers_snapshot_replay_and_heartbeat_paths(self) -> None:
        controller = StudioApiController(self._fake_conversation(), stream_buffer=StreamBuffer(max_frames=6))

        async def collect(cursor, headers=None):
            calls = {"count": 0}

            async def is_disconnected():
                calls["count"] += 1
                return calls["count"] > 1

            async def sleep(_seconds):
                return None

            request = SimpleNamespace(is_disconnected=is_disconnected, headers=headers or {})
            frames = []
            with patch("src.webapp_studio.backend.server.asyncio.sleep", sleep):
                async for frame in _stream_events(controller, request, cursor=cursor, run_id="run_01", agent_id="agent"):
                    frames.append(frame)
                    if len(frames) == 3:
                        break
            return frames

        initial = asyncio.run(collect(None))
        replay_cursor = controller.stream_buffer.latest_cursor()
        retained = controller.stream_buffer.publish("run.started", {"run_id": "run_01"})
        replayed = asyncio.run(collect(replay_cursor))
        last_event_id = retained.id
        header_retained = controller.stream_buffer.publish("queue.updated", {"items": []})
        header_replayed = asyncio.run(collect(None, {"last-event-id": last_event_id}))
        expired = asyncio.run(collect("event_seq:1"))

        self.assertIn("event: studio.hello", initial[0])
        self.assertIn("event: snapshot.replace", initial[1])
        self.assertIn("event: studio.heartbeat", initial[2])
        self.assertIn("event: studio.hello", replayed[0])
        self.assertIn(retained.id, replayed[1])
        self.assertIn("event: queue.updated", header_replayed[1])
        self.assertIn(header_retained.id, header_replayed[1])
        self.assertIn("event: snapshot.replace", expired[1])

    def test_stream_event_generator_polls_snapshot_changes_between_heartbeats(self) -> None:
        fake = self._fake_conversation()
        original_state = fake.state
        calls = {"count": 0}

        def changing_state():
            calls["count"] += 1
            snapshot = original_state()
            if calls["count"] > 1:
                snapshot["events"].append(
                    {
                        "id": "event_02",
                        "team_id": "team",
                        "conversation_id": "thread",
                        "seq": 2,
                        "created_at": "2026-06-01T10:00:01Z",
                        "author_id": "agent",
                        "author_kind": "agent",
                        "content": "changed",
                        "mentions": [],
                        "attachments": [],
                        "source_thread_id": "thread:mention:agent",
                        "source_message_id": "message_01",
                        "metadata": {},
                    }
                )
            return snapshot

        fake.state = changing_state
        controller = StudioApiController(fake, stream_buffer=StreamBuffer(max_frames=8))

        async def collect():
            async def is_disconnected():
                return False

            async def sleep(_seconds):
                return None

            request = SimpleNamespace(is_disconnected=is_disconnected, headers={})
            frames = []
            with patch("src.webapp_studio.backend.server.asyncio.sleep", sleep):
                async for frame in _stream_events(controller, request, cursor=None, run_id=None, agent_id=None):
                    frames.append(frame)
                    if len(frames) == 4:
                        break
            return frames

        frames = asyncio.run(collect())

        self.assertIn("event: studio.hello", frames[0])
        self.assertIn("event: snapshot.replace", frames[1])
        self.assertIn("event: snapshot.replace", frames[2])
        self.assertIn("event_02", frames[2])
        self.assertIn("event: studio.heartbeat", frames[3])

    def test_stream_event_generator_emits_specific_snapshot_diff_events(self) -> None:
        controller = StudioApiController(self._fake_conversation(), stream_buffer=StreamBuffer(max_frames=12))
        initial_snapshot = controller.state().model_dump(mode="json")
        initial_snapshot["activity"]["private_threads"] = []
        initial_snapshot["history"]["checkpoints"] = {}
        changed_snapshot = json.loads(json.dumps(initial_snapshot))
        changed_snapshot["activity"]["private_threads"] = [
            {
                "agent_id": "agent",
                "thread_id": "thread:mention:agent",
                "messages": [{"type": "ai", "name": "agent", "content": "working", "tool_calls": []}],
            }
        ]
        changed_snapshot["history"]["checkpoints"] = [
            {
                "id": "checkpoint_new",
                "thread_id": "thread:mention:agent",
                "checkpoint_ns": "",
                "parent_checkpoint_id": None,
                "seq": 1,
                "created_at": "2026-06-01T10:00:02Z",
                "source": "langgraph_sqlite",
                "metadata": {},
                "summary": {"agent_id": "agent"},
                "capabilities": {
                    "inspect": "available",
                    "resume": "available",
                    "branch_from_here": "available",
                },
            }
        ]
        changed_snapshot["generated_ui"] = [
            {
                "id": "generated_ui_live",
                "version": "studio.generated-ui.v1",
                "root": "metric_01",
                "elements": {
                    "metric_01": {
                        "component": "metric",
                        "props": {"label": "Tasks", "value": 2},
                    }
                },
                "state": {},
                "actions": {},
                "status": "valid",
                "errors": [],
                "created_at": "2026-06-01T10:00:05Z",
                "updated_at": None,
            }
        ]
        snapshots = [initial_snapshot, changed_snapshot]
        calls = {"count": 0}

        def state():
            index = min(calls["count"], len(snapshots) - 1)
            calls["count"] += 1
            snapshot = json.loads(json.dumps(snapshots[index]))
            return SimpleNamespace(model_dump=lambda mode="json": snapshot)

        controller.state = state

        async def collect():
            async def is_disconnected():
                return False

            async def sleep(_seconds):
                return None

            request = SimpleNamespace(is_disconnected=is_disconnected, headers={})
            frames = []
            with patch("src.webapp_studio.backend.server.asyncio.sleep", sleep):
                async for frame in _stream_events(controller, request, cursor=None, run_id=None, agent_id=None):
                    frames.append(frame)
                    if len(frames) == 6:
                        break
            return frames

        frames = asyncio.run(collect())

        self.assertIn("event: studio.hello", frames[0])
        self.assertIn("event: snapshot.replace", frames[1])
        self.assertIn("event: activity.private_message.appended", frames[2])
        self.assertIn("thread:mention:agent", frames[2])
        self.assertIn("event: checkpoint.observed", frames[3])
        self.assertIn("checkpoint_new", frames[3])
        self.assertIn("event: generated_ui.validated", frames[4])
        self.assertIn("generated_ui_live", frames[4])
        self.assertIn("event: snapshot.replace", frames[5])

    def test_activity_redaction_preserves_shape(self) -> None:
        value = {
            "headers": {"authorization": "Bearer secret", "safe": "ok"},
            "tool_calls": [{"api_key": "secret", "arguments": {"topic": "ai"}}],
            "tuple": ({"token": "secret"},),
        }

        redacted = redact_sensitive_fields(value)

        self.assertEqual(redacted["headers"]["authorization"], "[redacted]")
        self.assertEqual(redacted["headers"]["safe"], "ok")
        self.assertEqual(redacted["tool_calls"][0]["api_key"], "[redacted]")
        self.assertEqual(redacted["tool_calls"][0]["arguments"]["topic"], "ai")
        self.assertEqual(redacted["tuple"][0]["token"], "[redacted]")

    def test_state_factory_handles_empty_and_queued_edge_shapes(self) -> None:
        state = self._fake_conversation().state()
        state["participant_aliases"] = {"agent": ["lead"]}
        state["events"] = []
        state["agent_states"][0]["running"] = False
        state["agent_states"][0]["queued"] = True
        state["agent_states"][0]["queued_after_seq"] = 99
        state["private_thread_id"] = "plain-thread"
        state["private_messages"] = []

        factory = StudioStateFactory()
        studio_state = factory.from_legacy_state(state)

        self.assertEqual(studio_state.participant_aliases, {"agent": ["lead"]})
        self.assertTrue(studio_state.history.branches[0].created_at.endswith("Z"))
        self.assertIsNone(studio_state.runs[0].cursor)
        self.assertIsNone(studio_state.queue[0].message_event_id)
        self.assertTrue(studio_state.queue[0].can_cancel)
        self.assertIsNone(studio_state.activity.private_threads[0].agent_id)
        self.assertEqual(
            StudioStateFactory().from_legacy_state(
                state,
                private_activity_states=[state],
            ).activity.private_threads,
            studio_state.activity.private_threads,
        )
        self.assertIsNone(factory._event_id_for_seq(state, None))
        self.assertEqual(factory._event_id_for_seq(self._fake_conversation().state(), 1), "event_01")

    def test_state_factory_extracts_generated_ui_specs_from_event_metadata(self) -> None:
        state = self._fake_conversation().state()
        spec = {
            "id": "generated_ui_live",
            "version": "studio.generated-ui.v1",
            "root": "metric_01",
            "elements": {
                "metric_01": {
                    "component": "metric",
                    "props": {
                        "label": "Tasks",
                        "value": 2,
                    },
                },
            },
            "state": {},
            "actions": {},
            "status": "valid",
            "errors": [],
            "created_at": "2026-06-01T10:00:05Z",
            "updated_at": None,
        }
        state["events"][0]["metadata"] = {
            "generated_ui_specs": [
                spec,
                {"id": "missing-required-fields"},
                "not-a-spec",
            ]
        }
        state["events"].append(
            {
                **state["events"][0],
                "id": "event_02",
                "seq": 2,
                "metadata": {
                    "generated_ui": {
                        **spec,
                        "status": "invalid",
                        "errors": ["unknown component"],
                    }
                },
            }
        )
        studio_state = StudioStateFactory().from_legacy_state(state)

        self.assertEqual(len(studio_state.generated_ui), 1)
        self.assertEqual(studio_state.generated_ui[0].id, "generated_ui_live")
        self.assertEqual(studio_state.generated_ui[0].status, "invalid")
        self.assertEqual(studio_state.generated_ui[0].errors, ["unknown component"])
        self.assertEqual(StudioStateFactory()._generated_ui({"events": [{"metadata": "not-a-dict"}]}), [])

    def test_state_factory_derives_recent_runs_from_delivery_history(self) -> None:
        state = self._fake_conversation(running=False).state()
        state["deliveries"] = [
            {
                "id": "delivery_success",
                "team_id": "team",
                "conversation_id": "thread",
                "agent_id": "agent",
                "run_id": "run_success",
                "snapshot_seq": 1,
                "status": "success",
                "created_at": "2026-06-01T10:00:01Z",
                "completed_at": "2026-06-01T10:00:02Z",
                "error": None,
            },
            {
                "id": "delivery_ignored",
                "team_id": "team",
                "conversation_id": "thread",
                "agent_id": "agent",
                "run_id": "run_ignored",
                "snapshot_seq": 2,
                "status": "ignored",
                "created_at": "2026-06-01T10:00:03Z",
                "completed_at": "2026-06-01T10:00:04Z",
                "error": None,
            },
            {
                "id": "delivery_stopped",
                "team_id": "team",
                "conversation_id": "thread",
                "agent_id": "agent",
                "run_id": "run_stopped",
                "snapshot_seq": 3,
                "status": "stopped",
                "created_at": "2026-06-01T10:00:05Z",
                "completed_at": "2026-06-01T10:00:06Z",
                "error": None,
            },
            {
                "id": "delivery_failed",
                "team_id": "team",
                "conversation_id": "thread",
                "agent_id": "agent",
                "run_id": "run_failed",
                "snapshot_seq": 4,
                "status": "failed",
                "created_at": "2026-06-01T10:00:07Z",
                "completed_at": "2026-06-01T10:00:08Z",
                "error": "boom",
            },
            {
                "id": "delivery_no_run",
                "team_id": "team",
                "conversation_id": "thread",
                "agent_id": "agent",
                "run_id": None,
                "snapshot_seq": 5,
                "status": "success",
                "created_at": "2026-06-01T10:00:09Z",
                "completed_at": "2026-06-01T10:00:10Z",
                "error": None,
            },
        ]

        studio_state = StudioStateFactory().from_legacy_state(state)

        self.assertEqual([run.id for run in studio_state.runs], ["run_failed", "run_stopped", "run_ignored", "run_success"])
        self.assertEqual(studio_state.runs[0].status, "failed")
        self.assertEqual(studio_state.runs[0].metadata["delivery_id"], "delivery_failed")
        self.assertEqual(studio_state.runs[1].status, "stopped")
        self.assertEqual(studio_state.runs[2].status, "superseded")
        self.assertEqual(studio_state.runs[3].status, "completed")

    def test_controller_direct_edges(self) -> None:
        controller = StudioApiController(self._fake_conversation())
        checkpoint = CheckpointSummary(
            id="checkpoint_01",
            thread_id="thread",
            seq=1,
            created_at="2026-06-01T10:00:00Z",
            source="fixture",
        )
        controller.checkpoints = lambda: [checkpoint]

        self.assertEqual(controller.checkpoint("checkpoint_01").id, "checkpoint_01")
        self.assertEqual(controller.switch_branch("branch_main")[0].id, "branch_main")
        self.assertEqual(controller._version("package-that-does-not-exist"), "unknown")
        no_run = ConversationDeliveryDto(
            id="delivery_no_run",
            team_id="team",
            conversation_id="thread",
            agent_id="agent",
            run_id=None,
            snapshot_seq=1,
            status="success",
            created_at="2026-06-01T10:00:00Z",
        )
        stopped = no_run.model_copy(
            update={
                "id": "delivery_stopped",
                "run_id": "run_stopped",
                "status": "stopped",
            }
        )
        ignored = no_run.model_copy(
            update={
                "id": "delivery_ignored",
                "run_id": "run_ignored",
                "status": "ignored",
            }
        )
        failed = no_run.model_copy(
            update={
                "id": "delivery_failed",
                "run_id": "run_failed",
                "status": "failed",
            }
        )

        controller._publish_delivery_state(no_run)
        self.assertIsNone(controller._run_from_delivery(no_run))
        self.assertEqual(controller._run_from_delivery(failed).status, "failed")
        self.assertEqual(controller._run_from_delivery(stopped).status, "stopped")
        self.assertEqual(controller._run_from_delivery(ignored).status, "superseded")
        with self.assertRaisesRegex(Exception, "agent_id"):
            controller.stop_agent("")
        with self.assertRaisesRegex(Exception, "current"):
            controller.create_branch(BranchCreateRequest())
        with self.assertRaisesRegex(Exception, "file not found"):
            controller.file_resource("../secret")

    def test_parse_main_and_main_guard(self) -> None:
        args = parse_args(
            [
                "team.yaml",
                "--thread-id",
                "thread",
                "--host",
                "0.0.0.0",
                "--port",
                "9999",
                "--var",
                "topic=ai",
                "--no-env-file",
            ]
        )
        self.assertEqual(args.team_file, "team.yaml")
        self.assertEqual(args.port, 9999)

        with patch("src.webapp_studio.backend.application.studio_backend_launcher.StudioBackendLauncher") as launcher:
            self.assertEqual(main(["team.yaml", "--thread-id", "thread", "--var", "topic=ai"]), 0)
        self.assertEqual(launcher.return_value.launch.call_args.kwargs["variables"], {"topic": "ai"})

        output = io.StringIO()
        with patch.object(sys, "argv", ["server.py", "--help"]), self.assertRaises(SystemExit) as raised:
            with patch("sys.stdout", output):
                runpy.run_module("src.webapp_studio.backend.server", run_name="__main__")
        self.assertEqual(raised.exception.code, 0)
        self.assertIn("Serve the Webapp Studio", output.getvalue())

    def test_backend_launcher_closes_team_for_missing_and_served_conversation(self) -> None:
        missing_team = SimpleNamespace(closed=False, conversation_for=lambda _conversation_id: None)
        missing_team.close = lambda: setattr(missing_team, "closed", True)

        served_conversation = self._fake_conversation()
        served_team = SimpleNamespace(closed=False, conversation_for=lambda _conversation_id: served_conversation)
        served_team.close = lambda: setattr(served_team, "closed", True)
        teams = [missing_team, served_team]

        def fake_instanciator(config_variables=None):
            return SimpleNamespace(instantiate=lambda _team_file, _variables: teams.pop(0))

        with patch("src.webapp_studio.backend.application.studio_backend_launcher.TeamInstanciator", fake_instanciator):
            with self.assertRaisesRegex(ValueError, "conversation"):
                StudioBackendLauncher().launch(team_file="team.yaml")

        with (
            patch("src.webapp_studio.backend.application.studio_backend_launcher.TeamInstanciator", fake_instanciator),
            patch("src.webapp_studio.backend.application.studio_backend_launcher.uvicorn.run") as run,
        ):
            StudioBackendLauncher().launch(team_file="team.yaml", variables={"topic": "ai"}, port=9999)

        self.assertTrue(missing_team.closed)
        self.assertTrue(served_team.closed)
        self.assertEqual(run.call_args.kwargs["port"], 9999)

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

    def _fake_conversation(
        self,
        *,
        connection: sqlite3.Connection | None = None,
        participants: list[str] | None = None,
        running: bool = True,
        queued: bool = False,
        queued_after_seq: int | None = None,
        branching: bool = False,
        interrupts: bool = False,
        attachments: list[dict[str, object]] | None = None,
        root_dir: Path | None = None,
        deliveries: list[dict[str, object]] | None = None,
    ):
        messages = []
        stopped = []
        cancelled = []
        cleared = []
        runtime_calls = []
        branch_store = ConversationStore(team_id="team", conversation_id="thread") if branching else None
        interrupt_store = ConversationStore(team_id="team", conversation_id="thread") if interrupts else None
        if interrupt_store is not None:
            interrupt_store.create_interrupt(
                kind="approve",
                payload={"action": "write_file"},
                run_id="run_01",
                agent_id="agent",
                checkpoint_id="checkpoint_01",
                interrupt_id="interrupt_01",
            )
        replay_events: list[ConversationEvent] = []
        runtime_state = {"mention_hook_enabled": True, "max_cascade_turns": 3}
        agent_state = {
            "team_id": "team",
            "conversation_id": "thread",
            "agent_id": "agent",
            "last_delivered_seq": 1,
            "running": running,
            "queued": queued,
            "queued_after_seq": queued_after_seq,
            "current_run_id": "run_01" if running else None,
            "current_snapshot_seq": 1 if running else None,
            "stop_requested": False,
            "last_identity_refresh_seq": 0,
            "token_estimate_since_identity_refresh": 128,
        }

        def state():
            seed_event = {
                "id": "event_01",
                "team_id": "team",
                "conversation_id": "thread",
                "branch_id": "branch_main",
                "logical_message_id": "event_01",
                "version_parent_event_id": None,
                "parent_event_id": None,
                "seq": 1,
                "created_at": "2026-06-01T10:00:00Z",
                "author_id": "human",
                "author_kind": "human",
                "content": "@agent seed",
                "mentions": ["agent"],
                "attachments": list(attachments or []),
                "source_thread_id": None,
                "source_message_id": None,
                "metadata": {},
            }
            return {
                "team_id": "team",
                "conversation_id": "thread",
                "participants": ["agent"] if participants is None else participants,
                "runtime": {
                    "team_id": "team",
                    "conversation_id": "thread",
                    **runtime_state,
                },
                "events": [seed_event, *[event.to_dict() for event in replay_events]],
                "agent_states": [dict(agent_state)],
                "deliveries": list(deliveries or []),
                "activities": [],
                "activity": None,
            }

        def activity(agent_id=None):
            snapshot = state()
            snapshot["private_thread_id"] = f"thread:mention:{agent_id}"
            snapshot["private_messages"] = [{"type": "ai", "name": agent_id, "content": "working", "tool_calls": []}]
            return snapshot

        def append_human_message(content, *, author_id, files, wait, metadata=None):
            message_files = list(files or ())
            messages.append((content, author_id, message_files, wait, metadata))
            event = ConversationEvent(
                id=f"event_{len(replay_events) + 2:02d}",
                team_id="team",
                conversation_id="thread",
                branch_id=branch_store.current_branch_id() if branch_store is not None else "branch_main",
                seq=len(replay_events) + 2,
                created_at="2026-06-01T10:00:01Z",
                author_id=author_id,
                author_kind="human",
                content=content,
                mentions=("agent",),
                attachments=tuple(message_files),
                source_thread_id=None,
                source_message_id=None,
                metadata=dict(metadata or {}),
            )
            replay_events.append(event)
            return SimpleNamespace(
                event=SimpleNamespace(to_dict=event.to_dict),
                deliveries=(
                    SimpleNamespace(
                        to_dict=lambda: {
                            "id": "delivery_01",
                            "team_id": "team",
                            "conversation_id": "thread",
                            "branch_id": branch_store.current_branch_id() if branch_store is not None else "branch_main",
                            "agent_id": "agent",
                            "run_id": "run_01",
                            "snapshot_seq": 2,
                            "status": "success",
                            "created_at": "2026-06-01T10:00:02Z",
                            "completed_at": "2026-06-01T10:00:03Z",
                            "error": None,
                        }
                    ),
                ),
                failures=(),
            )

        def edit_human_message(event_id, content, *, author_id="human", wait=False):
            if branch_store is None:
                raise AssertionError("branching is not enabled for this fake conversation")
            if event_id != "event_01":
                raise ValueError("message event is not visible in the current branch.")
            branch = branch_store.create_branch(
                label="Edit #1",
                origin_event_id=event_id,
                origin_event_seq=0,
                parent_branch_id=branch_store.current_branch_id(),
            )
            branch_store.switch_branch(branch.id)
            event = ConversationEvent(
                id=f"event_edit_{len(replay_events) + 1}",
                team_id="team",
                conversation_id="thread",
                branch_id=branch.id,
                logical_message_id="event_01",
                version_parent_event_id="event_01",
                parent_event_id=None,
                seq=len(replay_events) + 2,
                created_at="2026-06-01T10:00:05Z",
                author_id=author_id,
                author_kind="human",
                content=content,
                mentions=("agent",),
                metadata={"edited_from_event_id": event_id},
            )
            replay_events.append(event)
            return SimpleNamespace(event=event, deliveries=(), failures=())

        def create_public_file_ref(*, filename, content, added_by, media_type=None):
            return SimpleNamespace(
                id=f"file_{len(messages) + 1}",
                filename=filename,
                uri=f"conversation://files/file_{len(messages) + 1}",
                media_type=media_type,
                size_bytes=len(content),
                added_by=added_by,
                to_dict=lambda: {
                    "id": f"file_{len(messages) + 1}",
                    "filename": filename,
                    "uri": f"conversation://files/file_{len(messages) + 1}",
                    "media_type": media_type,
                    "size_bytes": len(content),
                    "added_by": added_by,
                },
            )

        def set_mention_hook_enabled(enabled):
            runtime_calls.append(("hook", enabled))
            runtime_state["mention_hook_enabled"] = enabled
            return state()["runtime"]

        def set_max_cascade_turns(value):
            runtime_calls.append(("cascade", value))
            runtime_state["max_cascade_turns"] = value
            return state()["runtime"]

        def stop_agent(agent_id):
            stopped.append(agent_id)

        def cancel_queued_agent(agent_id):
            cancelled.append(agent_id)
            agent_state["queued"] = False
            agent_state["queued_after_seq"] = None
            return state()["runtime"]

        def clear_queue(scope="pending"):
            cleared.append(scope)
            if scope in {"pending", "all"}:
                agent_state["queued"] = False
                agent_state["queued_after_seq"] = None
            return state()["runtime"]

        def create_branch(
            *,
            label=None,
            origin_checkpoint_id=None,
            origin_event_id=None,
            origin_event_seq=None,
            head_checkpoint_id=None,
            parent_branch_id=None,
        ):
            if branch_store is None:
                raise AssertionError("branching is not enabled for this fake conversation")
            return branch_store.create_branch(
                label=label,
                origin_checkpoint_id=origin_checkpoint_id,
                origin_event_id=origin_event_id,
                origin_event_seq=origin_event_seq,
                head_checkpoint_id=head_checkpoint_id,
                parent_branch_id=parent_branch_id,
            )

        def list_branches():
            if branch_store is None:
                raise AssertionError("branching is not enabled for this fake conversation")
            return branch_store.list_branches()

        def current_branch_id():
            if branch_store is None:
                raise AssertionError("branching is not enabled for this fake conversation")
            return branch_store.current_branch_id()

        def switch_branch(branch_id):
            if branch_store is None:
                raise AssertionError("branching is not enabled for this fake conversation")
            return branch_store.switch_branch(branch_id)

        def resume_checkpoint(
            *,
            checkpoint_id,
            checkpoint_ns,
            thread_id,
            mode="resume",
            edited_content=None,
            origin_event_id=None,
            origin_event_seq=None,
        ):
            if branch_store is None:
                raise AssertionError("branching is not enabled for this fake conversation")
            branch = branch_store.create_branch(
                label=f"Checkpoint {mode}",
                origin_checkpoint_id=checkpoint_id,
                origin_event_id=origin_event_id,
                origin_event_seq=origin_event_seq,
                head_checkpoint_id=checkpoint_id,
                parent_branch_id=branch_store.current_branch_id(),
            )
            branch_store.switch_branch(branch.id)
            event = ConversationEvent(
                id=f"event_replay_{len(replay_events) + 1}",
                team_id="team",
                conversation_id="thread",
                branch_id=branch.id,
                seq=len(replay_events) + 2,
                created_at="2026-06-01T10:00:04Z",
                author_id="agent",
                author_kind="agent",
                content="checkpoint replay" if edited_content is None else edited_content,
                mentions=(),
                source_thread_id=thread_id,
                source_message_id="message_replay",
                metadata={"branch_id": branch.id, "checkpoint_id": checkpoint_id, "time_travel_mode": mode},
            )
            replay_events.append(event)
            return SimpleNamespace(branch=branch, event=event, mode=mode)

        def list_interrupts(active_only=True):
            if interrupt_store is None:
                raise AssertionError("interrupts are not enabled for this fake conversation")
            return interrupt_store.list_interrupts(active_only=active_only)

        def resume_interrupt(interrupt_id, *, decision, response=None, edited_payload=None):
            if interrupt_store is None:
                raise AssertionError("interrupts are not enabled for this fake conversation")
            return interrupt_store.resume_interrupt(
                interrupt_id,
                decision=decision,
                response=response,
                edited_payload=edited_payload,
            )

        runtime_methods = {
            "set_mention_hook_enabled": set_mention_hook_enabled,
            "set_max_cascade_turns": set_max_cascade_turns,
            "stop_agent": stop_agent,
            "cancel_queued_agent": cancel_queued_agent,
            "clear_queue": clear_queue,
        }
        if branching:
            runtime_methods.update(
                {
                    "create_branch": create_branch,
                    "list_branches": list_branches,
                    "current_branch_id": current_branch_id,
                    "switch_branch": switch_branch,
                    "edit_human_message": edit_human_message,
                    "resume_checkpoint": resume_checkpoint,
                }
            )
        if interrupts:
            runtime_methods.update(
                {
                    "list_interrupts": list_interrupts,
                    "resume_interrupt": resume_interrupt,
                }
            )

        fake = SimpleNamespace(
            checkpointer_handle=SimpleNamespace(connection=connection),
            root_dir=root_dir,
            state=state,
            activity=activity,
            append_human_message=append_human_message,
            create_public_file_ref=create_public_file_ref,
            runtime=SimpleNamespace(**runtime_methods),
        )
        fake.messages = messages
        fake.stopped = stopped
        fake.cancelled = cancelled
        fake.cleared = cleared
        fake.runtime_calls = runtime_calls
        return fake


if __name__ == "__main__":
    unittest.main()
