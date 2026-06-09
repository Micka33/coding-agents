from __future__ import annotations

import asyncio
import base64
import io
import json
import queue
import runpy
import sqlite3
import subprocess
import sys
import tempfile
import threading
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from fastapi.testclient import TestClient
from langchain_core.messages import AIMessage
from langgraph.checkpoint.serde.jsonplus import JsonPlusSerializer

from src.team_instanciator.configuration.runtime_configuration import RuntimeConfiguration
from src.team_instanciator.conversation import ConversationEvent, ConversationFileRef, ConversationStore
from src.team_instanciator.runtime.thread_id_factory import ThreadIdFactory
from src.team_loader.parsing.yaml_parser import YamlParser
from src.webapp_studio.backend.api.checkpoint_history_reader import CheckpointHistoryReader
from src.webapp_studio.backend.api.redactor import redact_sensitive_fields
from src.webapp_studio.backend.api.studio_attachment_ref_factory import (
    MAX_ATTACHMENT_BYTES,
    StudioAttachmentRefFactory,
)
from src.webapp_studio.backend.api.studio_api_controller import StudioApiController
from src.webapp_studio.backend.api.studio_api_error import StudioApiError
from src.webapp_studio.backend.api.studio_session_controller import StudioSessionController
from src.webapp_studio.backend.api.team_discovery_service import TeamDiscoveryService, duplicate_team_id_message
from src.webapp_studio.backend.api.studio_state_factory import StudioStateFactory
from src.webapp_studio.backend.api.studio_terminal_session import StudioTerminalSession
from src.webapp_studio.backend.api.studio_workspace_file_browser import StudioWorkspaceFileBrowser
from src.webapp_studio.backend.application.studio_backend_launcher import StudioBackendLauncher
from src.webapp_studio.backend.contracts.agent_prompt_inject_request import AgentPromptInjectRequest
from src.webapp_studio.backend.contracts.agent_delivery_state_dto import AgentDeliveryStateDto
from src.webapp_studio.backend.contracts.append_message_request import AppendMessageRequest
from src.webapp_studio.backend.contracts.branch_create_request import BranchCreateRequest
from src.webapp_studio.backend.contracts.checkpoint_summary import CheckpointSummary
from src.webapp_studio.backend.contracts.conversation_create_request import ConversationCreateRequest
from src.webapp_studio.backend.contracts.conversation_delivery_dto import ConversationDeliveryDto
from src.webapp_studio.backend.contracts.edit_message_request import EditMessageRequest
from src.webapp_studio.backend.contracts.runtime_update_request import RuntimeUpdateRequest
from src.webapp_studio.backend.contracts.studio_branch_ui_state_update_request import StudioBranchUiStateUpdateRequest
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
        self.assertEqual(activity["data"]["activity"]["private_threads"][0]["thread_id"], "thread:branch:branch_main:mention:agent")
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
            ["thread:branch:branch_main:mention:agent-a", "thread:branch:branch_main:mention:agent-b"],
        )
        self.assertEqual(
            [thread["messages"][0]["name"] for thread in state["data"]["activity"]["private_threads"]],
            ["agent-a", "agent-b"],
        )
        self.assertEqual(
            [thread["thread_id"] for thread in activity["data"]["activity"]["private_threads"]],
            ["thread:branch:branch_main:mention:agent-a"],
        )
        self.assertEqual(
            encoded_activity["data"]["activity"]["private_threads"][0]["thread_id"],
            "thread:branch:branch_main:mention:agent a",
        )

    def test_queue_controls_cancel_and_clear_pending_entries(self) -> None:
        cancel_fake = self._fake_conversation(running=False, queued=True, queued_after_seq=1)
        buffer = StreamBuffer()
        client = TestClient(create_app(cancel_fake, stream_buffer=buffer))

        queue = client.get("/api/studio/v1/queue").json()
        cancelled = client.delete(f"/api/studio/v1/queue/{queue['data'][0]['id']}").json()

        self.assertTrue(queue["data"][0]["can_cancel"])
        self.assertEqual(queue["data"][0]["branch_id"], "branch_main")
        self.assertEqual(cancelled["data"], [])
        self.assertEqual(cancel_fake.cancelled, [("agent", "branch_main")])
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
        self.assertEqual(queue["data"][0]["branch_id"], "branch_main")
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
            (files_dir / "file_markdown").write_bytes(b"# skill")
            (files_dir / "file_large_text").write_bytes(b"x" * (500 * 1024 + 1))
            (files_dir / "file_unknown").write_bytes(b"unknown")
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
                {
                    "id": "file_markdown",
                    "filename": "SKILL.md",
                    "uri": "conversation://files/file_markdown",
                    "media_type": None,
                    "size_bytes": 7,
                    "added_by": "human",
                },
                {
                    "id": "file_large_text",
                    "filename": "large.txt",
                    "uri": "conversation://files/file_large_text",
                    "media_type": "text/plain",
                    "size_bytes": 500 * 1024 + 1,
                    "added_by": "human",
                },
                {
                    "id": "file_unknown",
                    "filename": "unknown.bin",
                    "uri": "conversation://files/file_unknown",
                    "media_type": None,
                    "size_bytes": 7,
                    "added_by": "human",
                },
            ]
            client = TestClient(create_app(self._fake_conversation(attachments=attachments, root_dir=root_dir)))

            session = client.get("/api/studio/v1/session").json()
            conversations = client.get("/api/studio/v1/conversations?limit=10").json()
            files = client.get("/api/studio/v1/files").json()
            preview = client.get("/api/studio/v1/files/file_01/preview")
            markdown_preview = client.get("/api/studio/v1/files/file_markdown/preview")
            large_text_preview = client.get("/api/studio/v1/files/file_large_text/preview").json()
            unknown_preview = client.get("/api/studio/v1/files/file_unknown/preview").json()
            download = client.get("/api/studio/v1/files/file_html/download")
            changes = client.get("/api/studio/v1/changes").json()
            terminal = client.post("/api/studio/v1/terminal/sessions").json()
            terminal_output = client.get(
                f"/api/studio/v1/terminal/sessions/{terminal['data']['session_id']}/output"
            ).json()
            terminal_input = client.post(
                f"/api/studio/v1/terminal/sessions/{terminal['data']['session_id']}/input",
                json={"data": ""},
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
            files_by_id = {file["id"]: file for file in files["data"]["files"]}
            self.assertEqual(files_by_id["file_01"]["preview_mode"], "text")
            self.assertEqual(files_by_id["file_01"]["preview_url"], "/api/studio/v1/files/file_01/preview")
            self.assertEqual(files_by_id["file_01"]["download_url"], "/api/studio/v1/files/file_01/download")
            self.assertIsNone(files_by_id["file_html"]["preview_mode"])
            self.assertIsNone(files_by_id["file_html"]["preview_url"])
            self.assertEqual(files_by_id["file_markdown"]["media_type"], "text/markdown")
            self.assertEqual(files_by_id["file_markdown"]["preview_mode"], "text")
            self.assertEqual(files_by_id["file_markdown"]["preview_url"], "/api/studio/v1/files/file_markdown/preview")
            self.assertIsNone(files_by_id["file_large_text"]["preview_mode"])
            self.assertIsNone(files_by_id["file_large_text"]["preview_url"])
            self.assertIsNone(files_by_id["file_unknown"]["preview_mode"])
            self.assertIsNone(files_by_id["file_unknown"]["preview_url"])
            self.assertEqual(preview.content, b"hello")
            self.assertEqual(markdown_preview.content, b"# skill")
            self.assertIn("text/markdown", markdown_preview.headers["content-type"])
            self.assertEqual(large_text_preview["errors"][0]["code"], "unsupported_media_type")
            self.assertEqual(unknown_preview["errors"][0]["code"], "unsupported_media_type")
            self.assertEqual(download.content, b"<h1>x</h1>")
            self.assertEqual(changes["data"], {"changes": [], "supported": False})
            self.assertEqual(terminal["data"]["cwd"], str(root_dir.resolve()))
            self.assertEqual(terminal["data"]["status"], "running")
            self.assertIn("Terminal started", terminal_output["data"]["chunks"][0]["text"])
            self.assertEqual(terminal_input["data"]["status"], "running")
            self.assertEqual(resized_terminal["data"]["columns"], 120)
            self.assertEqual(resized_terminal["data"]["rows"], 40)
            self.assertEqual(stopped_terminal["data"]["status"], "terminated")

    def test_workspace_file_search_and_append_use_root_relative_paths(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root_dir = Path(temp_dir)
            source_dir = root_dir / "src"
            source_dir.mkdir()
            source_file = source_dir / "app.py"
            source_file.write_text("print('hello')\n", encoding="utf-8")
            large_file = root_dir / "large.bin"
            large_file.write_bytes(b"x" * (MAX_ATTACHMENT_BYTES + 1))
            (root_dir / ".coding-agents").mkdir()
            (root_dir / ".coding-agents" / "hidden.txt").write_text("hidden\n", encoding="utf-8")
            fake = self._fake_conversation(root_dir=root_dir)
            client = TestClient(create_app(fake))

            files = client.get("/api/studio/v1/workspace-files?query=app&limit=5").json()
            large_files = client.get("/api/studio/v1/workspace-files?query=large&limit=5").json()
            appended = client.post(
                "/api/studio/v1/messages",
                json={
                    "content": "@agent see source",
                    "author_id": "human",
                    "workspace_paths": ["src/app.py"],
                },
            ).json()
            traversal = client.post(
                "/api/studio/v1/messages",
                json={
                    "content": "@agent bad path",
                    "author_id": "human",
                    "workspace_paths": ["../secret.txt"],
                },
            ).json()
            absolute = client.post(
                "/api/studio/v1/messages",
                json={
                    "content": "@agent absolute path",
                    "author_id": "human",
                    "workspace_paths": [str(source_file.resolve())],
                },
            ).json()
            directory = client.post(
                "/api/studio/v1/messages",
                json={
                    "content": "@agent directory path",
                    "author_id": "human",
                    "workspace_paths": ["src"],
                },
            ).json()
            missing = client.post(
                "/api/studio/v1/messages",
                json={
                    "content": "@agent missing path",
                    "author_id": "human",
                    "workspace_paths": ["missing.txt"],
                },
            ).json()
            oversized = client.post(
                "/api/studio/v1/messages",
                json={
                    "content": "@agent large file",
                    "author_id": "human",
                    "workspace_paths": ["large.bin"],
                },
            ).json()

            self.assertEqual(files["data"]["files"][0]["path"], "src/app.py")
            self.assertEqual(files["data"]["files"][0]["filename"], "app.py")
            self.assertNotIn("hidden.txt", [item["path"] for item in files["data"]["files"]])
            self.assertEqual(large_files["data"]["files"], [])
            self.assertEqual(appended["data"]["event"]["attachments"][0]["filename"], "app.py")
            self.assertEqual(fake.messages[0][2][0].filename, "app.py")
            self.assertEqual(fake.messages[0][2][0].size_bytes, source_file.stat().st_size)
            self.assertEqual(traversal["errors"][0]["code"], "invalid_request")
            self.assertEqual(traversal["errors"][0]["field"], "workspace_paths")
            self.assertEqual(absolute["errors"][0]["message"], "workspace path must be relative.")
            self.assertEqual(directory["errors"][0]["message"], "workspace path must be a file.")
            self.assertEqual(missing["errors"][0]["code"], "not_found")
            self.assertEqual(oversized["errors"][0]["message"], "workspace file exceeds the 10 MiB limit.")

    def test_workspace_file_search_uses_git_excludes_when_available(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root_dir = Path(temp_dir)
            subprocess.run(["git", "-C", str(root_dir), "init"], check=True, capture_output=True)
            (root_dir / ".gitignore").write_text("ignored.txt\n", encoding="utf-8")
            (root_dir / "tracked.txt").write_text("tracked\n", encoding="utf-8")
            (root_dir / "untracked.txt").write_text("untracked\n", encoding="utf-8")
            (root_dir / "ignored.txt").write_text("ignored\n", encoding="utf-8")
            subprocess.run(["git", "-C", str(root_dir), "add", ".gitignore", "tracked.txt"], check=True)
            client = TestClient(create_app(self._fake_conversation(root_dir=root_dir)))

            files = client.get("/api/studio/v1/workspace-files?limit=10").json()
            paths = {item["path"] for item in files["data"]["files"]}

            self.assertIn("tracked.txt", paths)
            self.assertIn("untracked.txt", paths)
            self.assertNotIn("ignored.txt", paths)

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
        self.assertEqual(state["data"]["interrupts"][0]["branch_id"], "branch_main")
        self.assertEqual(pending["data"][0]["payload"]["action"], "write_file")
        self.assertEqual(resumed["data"]["interrupts"], [])
        self.assertEqual(fake.runtime.list_interrupts(active_only=False)[0].decisions[0]["response"], "approved with notes")
        self.assertEqual(missing["errors"][0]["field"], "interrupt_id")
        self.assertIn("interrupt.resolved", [frame.event for frame in buffer.replay_after(None) or []])

    def test_checkpoint_history_reads_langgraph_sqlite_rows(self) -> None:
        with sqlite3.connect(":memory:", check_same_thread=False) as connection:
            self._create_checkpoint_tables(connection)
            serde = JsonPlusSerializer()
            thread_factory = ThreadIdFactory()
            root_thread_id = thread_factory.root(team_id="team", conversation_id="thread")
            main_thread_id = thread_factory.mention(thread_factory.branch(root_thread_id, "branch_main"), "agent")
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
                    main_thread_id,
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
                (main_thread_id,),
            )
            connection.execute(
                """
                insert into writes (thread_id, checkpoint_ns, checkpoint_id, task_id, idx, channel, type, value)
                values (?, '', 'checkpoint_02', 'task', 0, 'messages', ?, ?)
                """,
                (main_thread_id, write_type, write_blob),
            )
            relation_thread_id = f"{main_thread_id}:relation:rel_worker:agent:worker"
            other_branch_thread_id = f"{thread_factory.mention(thread_factory.branch(root_thread_id, 'branch_other'), 'agent')}:relation:rel_worker:agent:worker"
            connection.execute(
                """
                insert into checkpoints (thread_id, checkpoint_ns, checkpoint_id, parent_checkpoint_id, type, checkpoint, metadata)
                values (?, '', 'checkpoint_03', null, null, null, null)
                """,
                (relation_thread_id,),
            )
            connection.execute(
                """
                insert into checkpoints (thread_id, checkpoint_ns, checkpoint_id, parent_checkpoint_id, type, checkpoint, metadata)
                values (?, '', 'checkpoint_04', null, null, null, null)
                """,
                (other_branch_thread_id,),
            )
            connection.execute(
                """
                insert into checkpoints (thread_id, checkpoint_ns, checkpoint_id, parent_checkpoint_id, type, checkpoint, metadata)
                values (?, '', 'checkpoint_unscoped_global', null, null, null, null)
                """,
                ("thread:mention:agent",),
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
            relation_history = CheckpointHistoryReader().checkpoints(
                fake,
                {
                    **fake.state(),
                    "branch_threads": [
                        {
                            "branch_id": "branch_main",
                            "physical_thread_id": relation_thread_id,
                        },
                        {
                            "branch_id": "branch_other",
                            "physical_thread_id": other_branch_thread_id,
                        },
                    ],
                },
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
            self.assertEqual([checkpoint.id for checkpoint in relation_history], ["checkpoint_01", "checkpoint_02", "checkpoint_03"])
            self.assertNotIn("checkpoint_unscoped_global", [checkpoint["id"] for checkpoint in checkpoints["data"]])
            self.assertEqual(relation_history[2].thread_id, relation_thread_id)
            self.assertEqual(relation_history[2].summary["agent_id"], "worker")

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
            thread_factory = ThreadIdFactory()
            root_thread_id = thread_factory.root(team_id="team", conversation_id="thread")
            main_thread_id = thread_factory.mention(thread_factory.branch(root_thread_id, "branch_main"), "agent")
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
                values (?, '', 'checkpoint_01', null, ?, ?, null)
                """,
                (main_thread_id, checkpoint_type, checkpoint_blob),
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
            checkpoints = client.get("/api/studio/v1/checkpoints").json()
            missing_branch = client.post("/api/studio/v1/branches/branch_missing/switch").json()
            switched = client.post(f"/api/studio/v1/branches/{created['data']['id']}/switch").json()
            state = client.get("/api/studio/v1/state").json()

            self.assertEqual(created["capabilities"]["branching"], "available")
            self.assertEqual(created["capabilities"]["time_travel"], "available")
            self.assertEqual(checkpoints["data"][0]["capabilities"]["branch_from_here"], "available")
            self.assertEqual(checkpoints["data"][0]["capabilities"]["resume"], "available")
            self.assertEqual(created["data"]["label"], "Alternative")
            self.assertEqual(created["data"]["parent_branch_id"], "branch_main")
            self.assertEqual(created["data"]["origin_checkpoint_id"], "checkpoint_01")
            self.assertEqual(created["data"]["origin_logical_message_id"], "event_01")
            self.assertFalse(created["data"]["current"])
            self.assertEqual(current_created["data"]["origin_checkpoint_id"], "checkpoint_01")
            self.assertEqual(message_created["data"]["origin_checkpoint_id"], "checkpoint_01")
            self.assertEqual(message_created["data"]["origin_logical_message_id"], "event_01")
            self.assertEqual(missing_message["errors"][0]["field"], "message_id")
            self.assertEqual(missing_checkpoint["errors"][0]["code"], "not_found")
            self.assertEqual(missing_branch["errors"][0]["field"], "branch_id")
            self.assertEqual(state["data"]["history"]["current_branch_id"], created["data"]["id"])
            self.assertTrue([item for item in switched["data"] if item["id"] == created["data"]["id"]][0]["current"])
            self.assertIn("branch.updated", [frame.event for frame in buffer.replay_after(None) or []])

            client.post("/api/studio/v1/branches/branch_main/switch")
            resumed = client.post("/api/studio/v1/checkpoints/checkpoint_01/resume", json={"mode": "resume"}).json()
            branch_events = [
                event
                for event in resumed["data"]["conversation"]["events"]
                if event["metadata"].get("time_travel_mode") == "resume"
            ]

            self.assertEqual(resumed["data"]["history"]["current_branch_id"], branch_events[0]["metadata"]["branch_id"])
            self.assertEqual(branch_events[0]["content"], "checkpoint replay")

            client.post("/api/studio/v1/branches/branch_main/switch")
            edited = client.post(
                "/api/studio/v1/checkpoints/checkpoint_01/resume",
                json={"mode": "edit", "edited_content": "edited checkpoint reply"},
            ).json()
            client.post("/api/studio/v1/branches/branch_main/switch")
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
                values ('thread:branch:branch_main:mention:agent', '', 'checkpoint_01', null, null, null, null)
                """
            )
            unmatched_connection.commit()
            unmatched_client = TestClient(create_app(self._fake_conversation(connection=unmatched_connection, branching=True)))
            unsupported_message = unmatched_client.post(
                "/api/studio/v1/branches",
                json={"label": "Unmatched message", "message_id": "event_01"},
            ).json()

            self.assertEqual(unsupported_message["errors"][0]["details"]["capability"], "branching")

    def test_branch_archiving_is_logical_and_excludes_active_history(self) -> None:
        fake = self._fake_conversation(branching=True)
        archived_candidate = fake.runtime.create_branch(label="Archive me", parent_branch_id="branch_main")
        current = fake.runtime.create_branch(label="Current", parent_branch_id="branch_main")
        fake.runtime.switch_branch(current.id)
        buffer = StreamBuffer()
        client = TestClient(create_app(fake, stream_buffer=buffer))

        current_error = client.post(f"/api/studio/v1/branches/{current.id}/archive").json()
        client.post("/api/studio/v1/branches/branch_main/switch")
        archived = client.post(f"/api/studio/v1/branches/{archived_candidate.id}/archive").json()
        archived_again = client.post(f"/api/studio/v1/branches/{archived_candidate.id}/archive").json()
        switch_archived = client.post(f"/api/studio/v1/branches/{archived_candidate.id}/switch").json()
        main_error = client.post("/api/studio/v1/branches/branch_main/archive").json()
        missing = client.post("/api/studio/v1/branches/branch_missing/archive").json()
        all_branches = fake.runtime.list_branches(include_archived=True)
        stream_events = [frame.event for frame in buffer.replay_after(None) or []]

        self.assertEqual(current_error["errors"][0]["code"], "invalid_request")
        self.assertEqual(main_error["errors"][0]["field"], "branch_id")
        self.assertEqual(missing["errors"][0]["code"], "not_found")
        self.assertEqual(switch_archived["errors"][0]["field"], "branch_id")
        self.assertEqual([branch["id"] for branch in archived["data"]], ["branch_main", current.id])
        self.assertEqual(archived_again["data"], archived["data"])
        self.assertIsNotNone([branch for branch in all_branches if branch.id == archived_candidate.id][0].archived_at)
        self.assertIn("branch.archived", stream_events)
        self.assertIn("snapshot.replace", stream_events)

    def test_checkpoint_actions_require_usable_frontier_metadata_when_present(self) -> None:
        with sqlite3.connect(":memory:", check_same_thread=False) as connection:
            self._create_checkpoint_tables(connection)
            thread_factory = ThreadIdFactory()
            root_thread_id = thread_factory.root(team_id="team", conversation_id="thread")
            main_thread_id = thread_factory.mention(thread_factory.branch(root_thread_id, "branch_main"), "agent")
            connection.execute(
                """
                insert into checkpoints (thread_id, checkpoint_ns, checkpoint_id, parent_checkpoint_id, type, checkpoint, metadata)
                values (?, '', 'checkpoint_01', null, null, null, null)
                """,
                (main_thread_id,),
            )
            connection.execute(
                """
                insert into checkpoints (thread_id, checkpoint_ns, checkpoint_id, parent_checkpoint_id, type, checkpoint, metadata)
                values (?, '', 'checkpoint_02', 'checkpoint_01', null, null, null)
                """,
                (main_thread_id,),
            )
            connection.commit()
            runs = [
                {
                    "id": "run_stable",
                    "team_id": "team",
                    "conversation_id": "thread",
                    "branch_id": "branch_main",
                    "agent_id": "agent",
                    "logical_thread_key": "mention:agent",
                    "physical_thread_id": main_thread_id,
                    "status": "success",
                    "stop_kind": None,
                    "snapshot_seq": 1,
                    "started_at": "2026-06-01T10:00:01Z",
                    "completed_at": "2026-06-01T10:00:02Z",
                    "stable_checkpoint_id": "checkpoint_01",
                    "latest_checkpoint_id": "checkpoint_01",
                    "checkpoint_stability": "stable",
                    "usable_for_fork": True,
                    "usable_for_continue": True,
                    "commit_state": "committed",
                },
                {
                    "id": "run_unstable",
                    "team_id": "team",
                    "conversation_id": "thread",
                    "branch_id": "branch_main",
                    "agent_id": "agent",
                    "logical_thread_key": "mention:agent",
                    "physical_thread_id": main_thread_id,
                    "status": "stopped",
                    "stop_kind": "user",
                    "snapshot_seq": 2,
                    "started_at": "2026-06-01T10:00:03Z",
                    "completed_at": "2026-06-01T10:00:04Z",
                    "stable_checkpoint_id": None,
                    "latest_checkpoint_id": "checkpoint_02",
                    "checkpoint_stability": "unstable",
                    "usable_for_fork": False,
                    "usable_for_continue": False,
                    "commit_state": "committed",
                },
            ]
            thread_frontiers = [
                {
                    "frontier_id": "frontier_stable",
                    "team_id": "team",
                    "conversation_id": "thread",
                    "branch_id": "branch_main",
                    "event_id": "event_01",
                    "event_boundary": "after",
                    "logical_thread_key": "mention:agent",
                    "physical_thread_id": main_thread_id,
                    "checkpoint_id": "checkpoint_01",
                    "parent_logical_thread_key": None,
                    "usable_for_fork": True,
                    "usable_for_continue": True,
                    "created_at": "2026-06-01T10:00:02Z",
                },
                {
                    "frontier_id": "frontier_unstable",
                    "team_id": "team",
                    "conversation_id": "thread",
                    "branch_id": "branch_main",
                    "event_id": "event_01",
                    "event_boundary": "after",
                    "logical_thread_key": "mention:agent",
                    "physical_thread_id": main_thread_id,
                    "checkpoint_id": "checkpoint_02",
                    "parent_logical_thread_key": None,
                    "usable_for_fork": False,
                    "usable_for_continue": False,
                    "created_at": "2026-06-01T10:00:04Z",
                },
            ]
            client = TestClient(
                create_app(
                    self._fake_conversation(
                        connection=connection,
                        branching=True,
                        runs=runs,
                        thread_frontiers=thread_frontiers,
                    )
                )
            )

            checkpoints = client.get("/api/studio/v1/checkpoints").json()["data"]
            resumed_unstable = client.post(
                "/api/studio/v1/checkpoints/checkpoint_02/resume",
                json={"mode": "resume"},
            ).json()
            branched_unstable = client.post(
                "/api/studio/v1/branches",
                json={"label": "Unstable", "checkpoint_id": "checkpoint_02"},
            ).json()

            self.assertEqual(checkpoints[0]["capabilities"]["resume"], "available")
            self.assertEqual(checkpoints[0]["capabilities"]["branch_from_here"], "available")
            self.assertEqual(checkpoints[1]["capabilities"]["resume"], "unsupported")
            self.assertEqual(checkpoints[1]["capabilities"]["branch_from_here"], "unsupported")
            self.assertEqual(resumed_unstable["errors"][0]["details"]["capability"], "time_travel")
            self.assertEqual(branched_unstable["errors"][0]["details"]["capability"], "branching")

    def test_agent_prompt_injection_records_control_event_and_public_reply(self) -> None:
        fake = self._fake_conversation()
        buffer = StreamBuffer()
        client = TestClient(create_app(fake, stream_buffer=buffer))

        injected = client.post(
            "/api/studio/v1/agents/agent/prompt",
            json={"content": "continue privately", "wait": True},
        ).json()

        events = injected["data"]["conversation"]["events"]
        control_events = injected["data"]["conversation"]["control_events"]
        stream_events = [frame.event for frame in buffer.replay_after(None) or []]

        self.assertEqual(fake.injected_prompts, [("agent", "continue privately", True)])
        self.assertEqual(events[-1]["author_kind"], "agent")
        self.assertEqual(events[-1]["content"], "injected reply")
        self.assertEqual(control_events[0]["kind"], "prompt-injection")
        self.assertEqual(control_events[0]["content"], "continue privately")
        self.assertIn("conversation.event.appended", stream_events)
        self.assertIn("snapshot.replace", stream_events)

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
        current_branch = next(branch for branch in edited["data"]["history"]["branches"] if branch["id"] == current_branch_id)

        self.assertNotEqual(current_branch_id, "branch_main")
        self.assertEqual(current_branch["origin_logical_message_id"], "event_01")
        self.assertIsNone(current_branch["origin_previous_event_id"])
        self.assertEqual(events[0]["content"], "@agent edited")
        self.assertEqual(events[0]["branch_id"], current_branch_id)
        self.assertEqual(events[0]["logical_message_id"], "event_01")
        self.assertEqual(events[0]["version_parent_event_id"], "event_01")
        self.assertEqual(events[0]["frontier_before_event_id"], "frontier_event_01_before")
        self.assertEqual(missing["errors"][0]["field"], "message_id")
        stream_events = [frame.event for frame in buffer.replay_after(None) or []]
        self.assertIn("conversation.event.appended", stream_events)
        self.assertIn("branch.updated", stream_events)

    def test_branch_ui_state_persists_per_branch(self) -> None:
        fake = self._fake_conversation(branching=True)
        buffer = StreamBuffer()
        client = TestClient(create_app(fake, stream_buffer=buffer))

        main_saved = client.patch(
            "/api/studio/v1/ui-state",
            json={
                "branch_id": "branch_main",
                "participant_id": "human",
                "draft_content": "main draft",
                "outbox_state": [
                    {
                        "clientMessageId": "main",
                        "content": "hello",
                        "createdAt": "2026-06-01T10:00:00Z",
                        "fileNames": [],
                        "status": "sending",
                    }
                ],
                "editing_event_id": "event_01",
            },
        ).json()
        edited = client.post(
            "/api/studio/v1/messages/event_01/edit",
            json={"content": "@agent edited", "author_id": "human", "wait": False},
        ).json()
        branch_id = edited["data"]["history"]["current_branch_id"]
        branch_saved = client.patch(
            "/api/studio/v1/ui-state",
            json={
                "branch_id": branch_id,
                "participant_id": "human",
                "draft_content": "branch draft",
                "outbox_state": [],
                "selected_agent_id": "agent",
            },
        ).json()

        client.post("/api/studio/v1/branches/branch_main/switch")
        main_snapshot = client.get("/api/studio/v1/state").json()
        client.post(f"/api/studio/v1/branches/{branch_id}/switch")
        branch_snapshot = client.get("/api/studio/v1/state").json()

        self.assertEqual(main_saved["data"]["branch_id"], "branch_main")
        self.assertEqual(main_saved["data"]["draft_content"], "main draft")
        self.assertEqual(branch_saved["data"]["branch_id"], branch_id)
        self.assertEqual(branch_saved["data"]["draft_content"], "branch draft")
        self.assertEqual(main_snapshot["data"]["history"]["current_branch_id"], "branch_main")
        self.assertEqual(main_snapshot["data"]["ui_state"]["draft_content"], "main draft")
        self.assertEqual(main_snapshot["data"]["ui_state"]["editing_event_id"], "event_01")
        self.assertEqual(branch_snapshot["data"]["history"]["current_branch_id"], branch_id)
        self.assertEqual(branch_snapshot["data"]["ui_state"]["draft_content"], "branch draft")
        self.assertEqual(branch_snapshot["data"]["ui_state"]["selected_agent_id"], "agent")
        stream_events = [frame.event for frame in buffer.replay_after(None) or []]
        self.assertIn("studio.ui_state.updated", stream_events)

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
        self.assertEqual(activity["private_thread_id"], "thread:branch:branch_main:mention:agent")
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
            "/api/studio/v1/agents/{agent_id}/prompt",
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

    def test_studio_controller_direct_contract_fallbacks(self) -> None:
        controller = StudioApiController(self._fake_conversation())

        teams = controller.teams()

        self.assertEqual(teams["teams"][0]["team_id"], "team")
        self.assertIsNone(teams["teams"][0]["team_file"])
        with self.assertRaises(StudioApiError):
            controller.create_conversation(ConversationCreateRequest(team_id="team", initial_message="hello"))

        legacy_fake = self._fake_conversation()
        original_append = legacy_fake.append_human_message

        def legacy_append_human_message(content, *, author_id, files, wait):
            return original_append(content, author_id=author_id, files=files, wait=wait)

        legacy_fake.append_human_message = legacy_append_human_message
        legacy_controller = StudioApiController(legacy_fake)
        appended = legacy_controller.append_message(
            AppendMessageRequest(content="@agent legacy client", author_id="human", client_message_id="client_01")
        )

        self.assertEqual(appended.event.content, "@agent legacy client")
        self.assertEqual(legacy_fake.messages[0][4], None)

        switchable = self._fake_conversation()
        switched_to = []

        def with_conversation_id(conversation_id):
            switched_to.append(conversation_id)
            return self._fake_conversation()

        switchable.with_conversation_id = with_conversation_id
        switch_controller = StudioApiController(switchable)

        with self.assertRaises(StudioApiError):
            switch_controller.switch_conversation(" ")
        with self.assertRaises(StudioApiError):
            switch_controller.switch_conversation("thread", team_id="other")

        switched = switch_controller.switch_conversation(" next-thread ")

        self.assertEqual(switched_to, ["next-thread"])
        self.assertEqual(switched["session"]["conversation_id"], "thread")
        with self.assertRaises(StudioApiError):
            StudioApiController(self._fake_conversation()).switch_conversation("thread")

        noisy_fake = self._fake_conversation()
        noisy_fake.state = lambda: {
            "team_id": "team",
            "conversation_id": "thread",
            "events": [object(), {"attachments": [object(), {"filename": "missing-id"}]}],
        }

        self.assertEqual(StudioApiController(noisy_fake).files(), {"files": []})

        terminal_controller = StudioApiController(self._fake_conversation())
        terminal_controller._terminal_sessions["session"] = SimpleNamespace(write=lambda data: {"written": data})

        self.assertEqual(terminal_controller.terminal_input("session", "pwd\n"), {"written": "pwd\n"})
        with self.assertRaises(StudioApiError):
            terminal_controller.terminal_output("missing")

        prompt_controller = StudioApiController(self._fake_conversation())
        with self.assertRaises(StudioApiError):
            prompt_controller.inject_agent_prompt("", AgentPromptInjectRequest(content="go"))

        no_prompt_fake = self._fake_conversation()
        delattr(no_prompt_fake.runtime, "inject_agent_prompt")
        with self.assertRaises(StudioApiError):
            StudioApiController(no_prompt_fake).inject_agent_prompt("agent", AgentPromptInjectRequest(content="go"))

        value_prompt_fake = self._fake_conversation()

        def reject_prompt(_agent_id, _content, *, wait=False):
            raise ValueError("prompt rejected")

        value_prompt_fake.runtime.inject_agent_prompt = reject_prompt
        with self.assertRaises(StudioApiError):
            StudioApiController(value_prompt_fake).inject_agent_prompt("agent", AgentPromptInjectRequest(content="go"))

        with self.assertRaises(StudioApiError):
            StudioApiController(self._fake_conversation()).archive_branch("branch")

        archive_fake = self._fake_conversation(branching=True)

        def reject_archive(_branch_id):
            raise ValueError("bad branch")

        archive_fake.runtime.archive_branch = reject_archive
        with self.assertRaises(StudioApiError):
            StudioApiController(archive_fake).archive_branch("branch_bad")

        with self.assertRaises(StudioApiError):
            StudioApiController(self._fake_conversation()).update_ui_state(StudioBranchUiStateUpdateRequest())

        ui_fake = self._fake_conversation(branching=True)

        def reject_ui_state(**_kwargs):
            raise ValueError("bad ui state")

        ui_fake.runtime.save_studio_branch_ui_state = reject_ui_state
        with self.assertRaises(StudioApiError):
            StudioApiController(ui_fake).update_ui_state(StudioBranchUiStateUpdateRequest())

    def test_studio_controller_sqlite_conversation_and_git_helpers(self) -> None:
        with sqlite3.connect(":memory:", check_same_thread=False) as connection:
            connection.execute(
                """
                create table team_conversation_events (
                    team_id text not null,
                    conversation_id text not null,
                    seq integer not null,
                    created_at text not null,
                    author_id text not null,
                    author_kind text not null,
                    content text not null
                )
                """
            )
            connection.executemany(
                """
                insert into team_conversation_events (
                    team_id,
                    conversation_id,
                    seq,
                    created_at,
                    author_id,
                    author_kind,
                    content
                ) values (?, ?, ?, ?, ?, ?, ?)
                """,
                [
                    ("team", "thread", 1, "2026-06-01T10:00:00Z", "human", "human", "hello from thread"),
                    ("team", "thread", 2, "2026-06-01T10:00:01Z", "agent", "agent", "reply"),
                    ("team", "agent-only", 1, "2026-06-01T10:00:02Z", "agent", "agent", "only agent"),
                ],
            )
            connection.commit()
            conversations = StudioApiController(self._fake_conversation(connection=connection)).conversations(limit=200)

        by_id = {item["conversation_id"]: item for item in conversations["conversations"]}

        self.assertEqual(conversations["current_conversation_id"], "thread")
        self.assertEqual(by_id["thread"]["title"], "hello from thread")
        self.assertEqual(by_id["thread"]["last_author_id"], "agent")
        self.assertEqual(by_id["agent-only"]["title"], "agent-only")

        with tempfile.TemporaryDirectory() as temp_dir:
            root_dir = Path(temp_dir)
            controller = StudioApiController(self._fake_conversation(root_dir=root_dir))
            parsed = controller._changes_from_git_status(
                b"X\0R  renamed.txt\0original.txt\0C  copied.txt\0source.txt\0"
            )

            self.assertEqual([item["status"] for item in parsed], ["renamed", "copied"])
            self.assertEqual(parsed[0]["source_path"], "original.txt")
            self.assertEqual(parsed[1]["source_path"], "source.txt")
            self.assertEqual(controller._change_status(" D"), "deleted")
            self.assertEqual(controller._change_status("R "), "renamed")
            self.assertEqual(controller._change_status("C "), "copied")
            self.assertEqual(controller._change_status("A "), "added")
            self.assertEqual(controller._change_status("!!"), "changed")
            self.assertIsNone(controller._change_by_id("missing"))
            with self.assertRaises(StudioApiError):
                controller.change_diff("missing")
            self.assertFalse(controller._path_is_within_root(root_dir.parent, root_dir))
            with self.assertRaises(StudioApiError):
                controller._git_diff_for_path(root_dir, "../outside.txt")

            missing_untracked_controller = StudioApiController(self._fake_conversation(root_dir=root_dir))
            missing_untracked_controller._change_by_id = lambda _change_id: {
                "status": "untracked",
                "path": "missing.txt",
            }

            self.assertEqual(missing_untracked_controller.change_diff("change")["diff"], "")

    def test_studio_controller_branch_checkpoint_and_helper_edges(self) -> None:
        edit_fake = self._fake_conversation(branching=True)
        edit_event = ConversationEvent(
            id="event_edit_delivery",
            team_id="team",
            conversation_id="thread",
            branch_id="branch_main",
            seq=2,
            created_at="2026-06-01T10:00:02Z",
            author_id="human",
            author_kind="human",
            content="@agent edited",
            mentions=("agent",),
        )

        def edit_with_delivery(_message_id, _content, *, author_id="human", wait=False):
            return SimpleNamespace(
                event=edit_event,
                deliveries=(
                    SimpleNamespace(
                        to_dict=lambda: {
                            "id": "delivery_edit",
                            "team_id": "team",
                            "conversation_id": "thread",
                            "branch_id": "branch_main",
                            "agent_id": "agent",
                            "run_id": None,
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

        edit_fake.runtime.edit_human_message = edit_with_delivery
        edited_state = StudioApiController(edit_fake).edit_message(
            "event_01",
            EditMessageRequest(content="@agent edited", author_id="human"),
        )

        self.assertEqual(edited_state.team_id, "team")

        controller = StudioApiController(self._fake_conversation())
        forkable, continuable, has_metadata = controller._checkpoint_usability(
            {
                "thread_frontiers": [
                    object(),
                    {"branch_id": "other", "checkpoint_id": "checkpoint_other"},
                    {"branch_id": "branch_main", "checkpoint_id": None},
                    {
                        "branch_id": "branch_main",
                        "physical_thread_id": "thread:branch:branch_main:mention:agent",
                        "checkpoint_id": "checkpoint_01",
                        "usable_for_fork": True,
                    },
                ],
                "runs": [
                    object(),
                    {"branch_id": "other", "stable_checkpoint_id": "checkpoint_other"},
                    {
                        "branch_id": "branch_main",
                        "physical_thread_id": "thread:branch:branch_main:mention:agent",
                        "stable_checkpoint_id": "checkpoint_02",
                        "latest_checkpoint_id": "checkpoint_02",
                        "commit_state": "pending",
                    },
                ],
            },
            current_branch_id="branch_main",
        )

        self.assertTrue(has_metadata)
        self.assertIn(("thread:branch:branch_main:mention:agent", "checkpoint_01"), forkable)
        self.assertEqual(continuable, set())
        self.assertEqual(controller._event_origin_metadata(None), (None, None))
        self.assertEqual(controller._event_origin_metadata("missing"), (None, None))
        self.assertEqual(controller._preview_mode("image.png", "image/png", 10), "iframe")
        self.assertEqual(controller._summary_text("   "), "Untitled conversation")
        self.assertEqual(controller._summary_text("x" * 81), f"{'x' * 77}...")
        self.assertEqual(controller._conversation_title([{"author_kind": "agent", "content": "reply"}]), "thread")
        self.assertIsNone(controller._team_file())
        team_file_controller = StudioApiController(self._fake_conversation())
        team_file_controller._conversation.team = SimpleNamespace(path="team.yaml")
        self.assertEqual(team_file_controller._team_file(), str((Path.cwd() / "team.yaml").resolve()))
        self.assertEqual(controller._resolved_root_dir(), Path.cwd().resolve())
        self.assertEqual(controller._optional_int("42"), 42)
        self.assertIsNone(controller._optional_int("forty-two"))

        noisy_state_fake = self._fake_conversation()
        noisy_state_fake.state = lambda: {
            "team_id": "team",
            "conversation_id": "thread",
            "events": [
                object(),
                {"metadata": "not a mapping"},
                {"metadata": {"client_message_id": "client_01"}, "author_id": "agent"},
            ],
        }

        self.assertIsNone(
            StudioApiController(noisy_state_fake)._event_for_client_message_id("client_01", "human")
        )

        class BrokenConnection:
            def execute(self, _sql):
                raise RuntimeError("database unavailable")

        self.assertIsNone(controller._sqlite_database_path(BrokenConnection()))
        with sqlite3.connect(":memory:") as memory_connection:
            self.assertIsNone(controller._sqlite_database_path(memory_connection))
        with tempfile.TemporaryDirectory() as temp_dir:
            sqlite_path = Path(temp_dir) / "history.sqlite"
            with sqlite3.connect(sqlite_path) as file_connection:
                self.assertEqual(controller._sqlite_database_path(file_connection), str(sqlite_path.resolve()))

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
                    "thread_id": "thread:branch:branch_main:mention:agent",
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
                        "source_thread_id": "thread:branch:branch_main:mention:agent",
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
                "thread_id": "thread:branch:branch_main:mention:agent",
                "messages": [{"type": "ai", "name": "agent", "content": "working", "tool_calls": []}],
            }
        ]
        changed_snapshot["history"]["checkpoints"] = [
            {
                "id": "checkpoint_new",
                "thread_id": "thread:branch:branch_main:mention:agent",
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
        self.assertIn("thread:branch:branch_main:mention:agent", frames[2])
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
        self.assertEqual(studio_state.queue[0].branch_id, "branch_main")
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
                "id": "delivery_interrupted",
                "team_id": "team",
                "conversation_id": "thread",
                "agent_id": "agent",
                "run_id": "run_interrupted",
                "snapshot_seq": 5,
                "status": "interrupted",
                "created_at": "2026-06-01T10:00:09Z",
                "completed_at": "2026-06-01T10:00:10Z",
                "error": None,
            },
            {
                "id": "delivery_no_run",
                "team_id": "team",
                "conversation_id": "thread",
                "agent_id": "agent",
                "run_id": None,
                "snapshot_seq": 6,
                "status": "success",
                "created_at": "2026-06-01T10:00:11Z",
                "completed_at": "2026-06-01T10:00:12Z",
                "error": None,
            },
        ]

        studio_state = StudioStateFactory().from_legacy_state(state)

        self.assertEqual([run.id for run in studio_state.runs], ["run_interrupted", "run_failed", "run_stopped", "run_ignored", "run_success"])
        self.assertEqual(studio_state.runs[0].status, "failed")
        self.assertEqual(studio_state.runs[0].metadata["delivery_id"], "delivery_interrupted")
        self.assertEqual(studio_state.runs[1].status, "failed")
        self.assertEqual(studio_state.runs[1].metadata["delivery_id"], "delivery_failed")
        self.assertEqual(studio_state.runs[2].status, "stopped")
        self.assertEqual(studio_state.runs[3].status, "superseded")
        self.assertEqual(studio_state.runs[4].status, "completed")

    def test_state_factory_includes_model_attempts(self) -> None:
        state = self._fake_conversation(running=False).state()
        state["model_attempts"] = [
            {
                "id": "model_attempt_01",
                "team_id": "team",
                "conversation_id": "thread",
                "branch_id": "branch_main",
                "run_id": "run_01",
                "agent_id": "agent",
                "provider": "openai",
                "model": "openai:gpt-test",
                "attempt_number": 2,
                "max_attempts": 3,
                "timeout_mode": "stream_idle_timeout",
                "timeout_seconds": 120,
                "started_at": "2026-06-01T10:00:01Z",
                "completed_at": "2026-06-01T10:00:02Z",
                "status": "retrying",
                "normalized_failure_code": "stream_idle_timeout",
                "provider_error_type": "TimeoutError",
            }
        ]

        studio_state = StudioStateFactory().from_legacy_state(state)

        self.assertEqual(studio_state.conversation.model_attempts[0].id, "model_attempt_01")
        self.assertEqual(studio_state.conversation.model_attempts[0].status, "retrying")
        self.assertEqual(studio_state.conversation.model_attempts[0].attempt_number, 2)

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

    def test_backend_launcher_prints_discovery_error_message(self) -> None:
        controller = SimpleNamespace(
            discovery_error_message=lambda: "duplicate team",
            close=lambda: setattr(controller, "closed", True),
        )

        with (
            patch("src.webapp_studio.backend.application.studio_backend_launcher.StudioSessionController", return_value=controller),
            patch("src.webapp_studio.backend.application.studio_backend_launcher.create_app", return_value="app"),
            patch("src.webapp_studio.backend.application.studio_backend_launcher.uvicorn.run"),
            patch("sys.stdout", new_callable=io.StringIO) as output,
        ):
            StudioBackendLauncher().launch(team_file="team.yaml", port=9999)

        self.assertIn("duplicate team", output.getvalue())
        self.assertTrue(controller.closed)

    def test_team_discovery_blocks_case_insensitive_duplicate_conversation_team_ids(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            workspace = root / "workspace"
            repository = root / "repo"
            self._write_discovery_team(workspace / ".coding-agents" / "teams" / "local" / "team.yaml", "OpenSpec")
            self._write_discovery_team(repository / "teams" / "builtin" / "team.yaml", "openspec")
            self._write_discovery_team(repository / "teams" / "batch" / "team.yaml", "OpenSpec", conversation=False)

            discovery = TeamDiscoveryService(repository_root=repository, workspace_dir=workspace).discover()

        self.assertEqual(discovery["status"], "blocked")
        self.assertEqual(len(discovery["duplicate_ids"]), 1)
        duplicate = discovery["duplicate_ids"][0]
        self.assertEqual(duplicate["normalized_id"], "openspec")
        self.assertEqual(len(duplicate["team_files"]), 2)

    def test_team_discovery_handles_invalid_descriptors_and_duplicate_messages(self) -> None:
        class StaticParser:
            def __init__(self, parsed):
                self.parsed = parsed

            def parse(self, _text):
                return self.parsed

        class UnreadablePath:
            def is_file(self):
                return True

            def read_text(self, *, encoding="utf-8"):
                raise OSError("unreadable")

            def __str__(self):
                return "/unreadable/team.yaml"

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            workspace = root / "workspace"
            repository = root / "repo"
            project_team = workspace / ".coding-agents" / "teams" / "local" / "team.yaml"
            self._write_discovery_team(project_team, "Local")

            discovery = TeamDiscoveryService(repository_root=repository, workspace_dir=workspace).discover(
                explicit_team_file=project_team
            )

            self.assertEqual(len(discovery["teams"]), 1)

            invalid_file = root / "invalid.yaml"
            invalid_file.write_text("[]", encoding="utf-8")
            self.assertIsNone(
                TeamDiscoveryService(
                    repository_root=repository,
                    workspace_dir=workspace,
                    yaml_parser=StaticParser([]),
                )._descriptor(invalid_file, "test")
            )
            self.assertIsNone(
                TeamDiscoveryService(
                    repository_root=repository,
                    workspace_dir=workspace,
                    yaml_parser=StaticParser({}),
                )._descriptor(invalid_file, "test")
            )
            self.assertIsNone(
                TeamDiscoveryService(repository_root=repository, workspace_dir=workspace)._descriptor(
                    UnreadablePath(),
                    "test",
                )
            )

            service = TeamDiscoveryService(
                repository_root=repository,
                workspace_dir=workspace,
                yaml_parser=StaticParser(
                    {
                        "id": "aliases",
                        "conversation": {},
                        "agents": {
                            "guide": {"kind": "deepagent", "conversation": "bad"},
                            "helper": {"kind": "subagent", "conversation": {}},
                            "broken": "bad",
                        },
                    }
                ),
            )
            descriptor = service._descriptor(invalid_file, "test")

        self.assertEqual(descriptor["participants"], ["guide"])
        self.assertEqual(descriptor["participant_aliases"], {"guide": []})
        self.assertEqual(service._participants({"agents": "bad"}), [])
        self.assertEqual(service._participant_aliases({"agents": "bad"}, ["guide"]), {})
        self.assertEqual(service._participant_aliases({"agents": {"guide": "bad"}}, ["guide"]), {})
        self.assertIsNone(duplicate_team_id_message({"duplicate_ids": []}))
        message = duplicate_team_id_message(
            {
                "duplicate_ids": [
                    {
                        "team_id": "Local",
                        "normalized_id": "local",
                        "team_files": ["/a/team.yaml", "/b/team.yaml"],
                    }
                ]
            }
        )
        self.assertIn('id "Local"', message)
        self.assertIn("/a/team.yaml", message)

    def test_workspace_file_browser_edge_branches(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            for index in range(6):
                (root / f"alpha-{index}.txt").write_text(str(index), encoding="utf-8")
            (root / "src").mkdir()
            (root / "src" / "target.py").write_text("print('x')\n", encoding="utf-8")
            (root / ".git").write_text("git-file", encoding="utf-8")
            browser = StudioWorkspaceFileBrowser(root)

            limited = browser.files(query="alpha", limit=1)

            self.assertEqual(len(limited["files"]), 1)
            with self.assertRaises(StudioApiError):
                browser.file_path("", field="workspace_paths")

            target = root / "alpha-0.txt"
            original_stat = Path.stat
            calls = {"count": 0}

            def flaky_stat(path, *args, **kwargs):
                if path.name == target.name:
                    calls["count"] += 1
                    if calls["count"] >= 4:
                        raise OSError("gone")
                return original_stat(path, *args, **kwargs)

            with patch.object(type(target), "stat", flaky_stat):
                with self.assertRaises(StudioApiError):
                    browser.file_path("alpha-0.txt", field="workspace_paths")

            with patch(
                "src.webapp_studio.backend.api.studio_workspace_file_browser.subprocess.run",
                return_value=SimpleNamespace(stdout=b"valid.txt\0\xff\0.git/config\0"),
            ):
                self.assertEqual(browser._git_workspace_file_candidates(), ["valid.txt"])

            with patch("src.webapp_studio.backend.api.studio_workspace_file_browser._MAX_WORKSPACE_SCAN_FILES", 1):
                scanned = browser._scanned_workspace_file_candidates()

            self.assertEqual(len(scanned), 1)
            self.assertTrue(scanned[0].startswith("alpha-"))
            self.assertNotIn(".git", browser._scanned_workspace_file_candidates())

            broken_item = SimpleNamespace(stat=lambda: (_ for _ in ()).throw(OSError("missing")))
            browser.file_path = lambda _relative_path, *, field: broken_item

            self.assertIsNone(browser._workspace_file_item("missing.txt"))
            self.assertEqual(
                StudioWorkspaceFileBrowser(root)._workspace_file_score(
                    {"path": "src/target.py", "filename": "target.py"},
                    "src",
                ),
                1,
            )
            self.assertEqual(
                StudioWorkspaceFileBrowser(root)._workspace_file_score(
                    {"path": "src/target.py", "filename": "target.py"},
                    "get",
                ),
                2,
            )
            self.assertEqual(
                StudioWorkspaceFileBrowser(root)._workspace_file_score(
                    {"path": "src/target.py", "filename": "target.py"},
                    "target.p",
                ),
                0,
            )
            self.assertEqual(
                StudioWorkspaceFileBrowser(root)._workspace_file_score(
                    {"path": "src/target.py", "filename": "target.py"},
                    "rc/tar",
                ),
                3,
            )

    def test_checkpoint_reader_terminal_and_state_factory_edges(self) -> None:
        reader = CheckpointHistoryReader()
        thread_factory = ThreadIdFactory()
        root_thread_id = thread_factory.root(team_id="team", conversation_id="thread")
        main_thread_id = thread_factory.mention(thread_factory.branch(root_thread_id, "branch_main"), "agent")
        other_thread_id = thread_factory.mention(thread_factory.branch(root_thread_id, "other"), "agent")
        relation_thread_id = f"{main_thread_id}:relation:rel_worker:agent:worker"

        self.assertEqual(
            reader._thread_ids(
                {
                    "team_id": "team",
                    "conversation_id": "thread",
                    "participants": ["agent"],
                    "branch_threads": [
                        object(),
                        {"branch_id": "other", "physical_thread_id": other_thread_id},
                        {"branch_id": "branch_main", "physical_thread_id": relation_thread_id},
                    ],
                },
                team_id="team",
                conversation_id="thread",
                branch_id="branch_main",
            ),
            [main_thread_id, relation_thread_id],
        )

        class BrokenCheckpointConnection:
            def execute(self, _sql, _args):
                raise sqlite3.OperationalError("database is locked")

        with self.assertRaises(sqlite3.OperationalError):
            reader.checkpoints(
                SimpleNamespace(checkpointer_handle=SimpleNamespace(connection=BrokenCheckpointConnection())),
                {"team_id": "team", "conversation_id": "thread", "participants": ["agent"]},
            )
        with sqlite3.connect(":memory:") as connection:
            self.assertEqual(reader._written_messages(connection, "thread", "", "checkpoint"), [])

        class BrokenWritesConnection:
            def execute(self, _sql, _args):
                raise sqlite3.OperationalError("database is locked")

        with self.assertRaises(sqlite3.OperationalError):
            reader._written_messages(BrokenWritesConnection(), "thread", "", "checkpoint")

        session = StudioTerminalSession.__new__(StudioTerminalSession)
        session.session_id = "term"
        session.cwd = Path.cwd()
        session.columns = 100
        session.rows = 30
        session.created_at = "2026-06-01T10:00:00Z"
        session._chunks = []
        session._lock = threading.Lock()
        session._output_queue = queue.Queue()

        session._process = SimpleNamespace(poll=lambda: 1, stdin=None, stdout=None)

        self.assertEqual(session.write("echo hi\n")["status"], "terminated")
        session._read_output()

        class FakeStdin:
            def __init__(self):
                self.data = b""
                self.flushed = False

            def write(self, data):
                self.data += data

            def flush(self):
                self.flushed = True

        stdin = FakeStdin()
        session._process = SimpleNamespace(poll=lambda: None, stdin=stdin, stdout=None)

        self.assertEqual(session.write("pwd\n")["status"], "running")
        self.assertEqual(stdin.data, b"pwd\n")
        self.assertTrue(stdin.flushed)

        class FakeStdout:
            def fileno(self):
                return 123

        session._process = SimpleNamespace(stdout=FakeStdout())
        with patch("src.webapp_studio.backend.api.studio_terminal_session.os.read", side_effect=OSError("closed")):
            session._read_output()

        self.assertIsNone(session._output_queue.get_nowait())

        session._output_queue = queue.Queue()
        reads = [b"hello", b""]

        def next_read(_descriptor, _size):
            return reads.pop(0)

        with patch("src.webapp_studio.backend.api.studio_terminal_session.os.read", next_read):
            session._read_output()

        self.assertEqual(session._output_queue.get_nowait(), b"hello")
        self.assertIsNone(session._output_queue.get_nowait())

        session._output_queue = queue.Queue()
        session._output_queue.put(b"drained")
        session._output_queue.put(None)
        session._drain_output()
        session._append_output("")

        self.assertEqual(session._chunks[-1]["text"], "drained")

        factory = StudioStateFactory()
        agent_state = AgentDeliveryStateDto.model_validate(
            {
                "team_id": "team",
                "conversation_id": "thread",
                "branch_id": "branch_main",
                "agent_id": "agent",
                "last_delivered_seq": 1,
                "running": True,
                "queued": False,
                "current_run_id": "run_01",
                "current_snapshot_seq": 1,
                "stop_requested": False,
                "last_identity_refresh_seq": 0,
                "token_estimate_since_identity_refresh": 0,
            }
        )
        runs = factory._runs(
            {
                "events": [],
                "runs": [
                    {
                        "id": "run_01",
                        "team_id": "team",
                        "conversation_id": "thread",
                        "branch_id": "branch_main",
                        "agent_id": "agent",
                        "status": "success",
                        "snapshot_seq": 1,
                        "started_at": "2026-06-01T10:00:00Z",
                        "completed_at": "2026-06-01T10:00:01Z",
                        "commit_state": "committed",
                    }
                ],
            },
            [agent_state],
            [],
        )

        self.assertEqual([run.id for run in runs], ["run_01"])
        self.assertEqual(factory._run_status_from_persisted("success", "orphaned"), "unknown")
        self.assertEqual(factory._run_status_from_persisted("running", "committed"), "running")
        self.assertEqual(factory._run_status_from_persisted("failed", "committed"), "failed")
        self.assertEqual(factory._run_status_from_persisted("ignored", "committed"), "superseded")

    def test_session_controller_starts_empty_and_creates_first_message_conversation(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            workspace = root / "workspace"
            repository = root / "repo"
            source_dir = workspace / "src"
            source_dir.mkdir(parents=True)
            source_file = source_dir / "app.py"
            source_file.write_text("print('draft')\n", encoding="utf-8")
            source_file_size = source_file.stat().st_size
            self._write_discovery_team(
                repository / "teams" / "alpha" / "team.yaml",
                "alpha",
                working_directory="project",
            )
            self._write_conversation_history(
                workspace / ".team-instanciator" / "checkpoints.sqlite",
                team_id="alpha",
                conversation_id="alpha-previous",
                content="previous plan",
            )
            created_conversations: list[str | None] = []
            dispatch_calls: list[tuple[str, bool]] = []

            def conversation_for(conversation_id: str | None):
                resolved_conversation_id = created_conversations.append(conversation_id) or str(conversation_id)
                conversation = self._fake_created_conversation(
                    team_id="alpha",
                    conversation_id=resolved_conversation_id,
                    root_dir=workspace,
                )
                conversation.dispatch_pending = lambda *, wait=False: dispatch_calls.append((resolved_conversation_id, wait))
                return conversation

            def instanciator_factory(config_variables=None):
                return SimpleNamespace(
                    instantiate=lambda _team_file, _variables: SimpleNamespace(
                        close=lambda: None,
                        conversation_for=conversation_for,
                    )
                )

            controller = StudioSessionController(
                repository_root=repository,
                workspace_dir=workspace,
                instanciator_factory=instanciator_factory,
            )
            client = TestClient(create_app(controller))

            teams = client.get("/api/studio/v1/teams").json()
            session = client.get("/api/studio/v1/session").json()
            history = client.get("/api/studio/v1/conversations").json()
            draft_files = client.get("/api/studio/v1/workspace-files?query=app&limit=5").json()
            missing_state = client.get("/api/studio/v1/state").json()
            created = client.post(
                "/api/studio/v1/conversations",
                json={
                    "team_id": "alpha",
                    "initial_message": "shape a thing",
                    "workspace_paths": ["src/app.py"],
                    "client_message_id": "client_01",
                },
            ).json()
            switched = client.put(
                "/api/studio/v1/session/conversation",
                json={"team_id": "alpha", "conversation_id": "alpha-existing"},
            ).json()

        self.assertEqual(teams["data"]["status"], "ready")
        self.assertEqual(teams["data"]["teams"][0]["team_id"], "alpha")
        self.assertEqual(teams["data"]["teams"][0]["participants"], ["guide", "reviewer"])
        self.assertNotIn("helper", teams["data"]["teams"][0]["participants"])
        self.assertEqual(teams["data"]["teams"][0]["participant_aliases"]["guide"], ["mentor"])
        self.assertEqual(teams["data"]["teams"][0]["participant_aliases"]["reviewer"], [])
        self.assertIsNone(session["data"]["conversation_id"])
        self.assertEqual(history["data"]["conversations"][0]["team_id"], "alpha")
        self.assertEqual(history["data"]["conversations"][0]["conversation_id"], "alpha-previous")
        self.assertEqual(history["data"]["conversations"][0]["title"], "previous plan")
        self.assertEqual(draft_files["data"]["files"][0]["path"], "src/app.py")
        self.assertEqual(missing_state["errors"][0]["code"], "conversation_required")
        self.assertTrue(created["data"]["session"]["conversation_id"].startswith("alpha-"))
        self.assertEqual(created["data"]["state"]["conversation"]["events"][0]["content"], "shape a thing")
        self.assertEqual(created["data"]["append"]["event"]["attachments"][0]["filename"], "app.py")
        self.assertEqual(created["data"]["append"]["event"]["attachments"][0]["size_bytes"], source_file_size)
        self.assertEqual(created["data"]["append"]["event"]["metadata"]["client_message_id"], "client_01")
        self.assertEqual(switched["data"]["session"]["conversation_id"], "alpha-existing")
        self.assertIn("alpha-existing", created_conversations)
        self.assertIn(("alpha-existing", False), dispatch_calls)

    def test_session_controller_delegates_and_handles_discovery_edge_cases(self) -> None:
        class Active:
            def __getattr__(self, name: str):
                def call(*args, **kwargs):
                    return {"method": name, "args": args, "kwargs": kwargs}

                return call

            def health(self):
                return "health"

            def session(self):
                return {"team_id": "alpha", "conversation_id": "thread"}

            def conversations(self, limit):
                return {"limit": limit}

            def workspace_files(self, *, query: str, limit: int):
                return {"query": query, "limit": limit}

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            team_file = root / "team.yaml"
            self._write_discovery_team(team_file, "alpha")
            controller = object.__new__(StudioSessionController)
            controller._repository_root = root
            controller._workspace_dir = root
            controller._team_file = None
            controller._variables = None
            controller._config_variables = None
            controller._stream_buffer = StreamBuffer()
            controller._instanciator_factory = None
            controller._started_at = "now"
            controller._discovery = {
                "status": "ready",
                "teams": [{"team_id": "alpha", "team_file": str(team_file)}],
            }
            controller._configuration = RuntimeConfiguration({"SQLITE_PATH": "configured.sqlite"})
            controller._yaml_parser = YamlParser()
            controller._instances = {}
            controller._active = Active()

            self.assertIsInstance(controller.stream_buffer, StreamBuffer)
            self.assertEqual(controller.health(), "health")
            self.assertEqual(controller.session()["team_id"], "alpha")
            self.assertEqual(controller.conversations(3), {"limit": 3})
            self.assertEqual(controller.activity("agent")["method"], "activity")
            self.assertEqual(controller.append_message(object())["method"], "append_message")
            self.assertEqual(controller.edit_message("message", object())["method"], "edit_message")
            self.assertEqual(controller.switch_conversation("thread")["method"], "switch_conversation")
            self.assertEqual(controller.files()["method"], "files")
            self.assertEqual(controller.workspace_files(query="app", limit=1), {"query": "app", "limit": 1})
            self.assertEqual(controller.changes()["method"], "changes")
            self.assertEqual(controller.change_diff("change")["method"], "change_diff")
            self.assertEqual(controller.create_terminal_session()["method"], "create_terminal_session")
            self.assertEqual(controller.terminal_output("terminal")["method"], "terminal_output")
            self.assertEqual(controller.terminal_input("terminal", "x")["method"], "terminal_input")
            self.assertEqual(controller.terminal_resize("terminal", columns=80, rows=24)["method"], "terminal_resize")
            self.assertEqual(controller.terminate_terminal_session("terminal")["method"], "terminate_terminal_session")
            self.assertEqual(controller.update_runtime(object())["method"], "update_runtime")
            self.assertEqual(controller.stop_agent("agent")["method"], "stop_agent")
            self.assertEqual(controller.inject_agent_prompt("agent", object())["method"], "inject_agent_prompt")
            self.assertEqual(controller.runs()["method"], "runs")
            self.assertEqual(controller.join_run("run")["method"], "join_run")
            self.assertEqual(controller.queue()["method"], "queue")
            self.assertEqual(controller.cancel_queue_item("item")["method"], "cancel_queue_item")
            self.assertEqual(controller.clear_queue(object())["method"], "clear_queue")
            self.assertEqual(controller.checkpoints()["method"], "checkpoints")
            self.assertEqual(controller.checkpoint("checkpoint")["method"], "checkpoint")
            self.assertEqual(controller.resume_checkpoint("checkpoint", object())["method"], "resume_checkpoint")
            self.assertEqual(controller.branches()["method"], "branches")
            self.assertEqual(controller.create_branch(object())["method"], "create_branch")
            self.assertEqual(controller.switch_branch("branch")["method"], "switch_branch")
            self.assertEqual(controller.archive_branch("branch")["method"], "archive_branch")
            self.assertEqual(controller.update_ui_state(object())["method"], "update_ui_state")
            self.assertEqual(controller.interrupts()["method"], "interrupts")
            self.assertEqual(controller.resume_interrupt("interrupt", object())["method"], "resume_interrupt")
            self.assertEqual(controller.file_resource("file", allow_blocked=True, preview=True)["method"], "file_resource")
            self.assertEqual(controller.compat_state()["method"], "compat_state")
            self.assertEqual(controller.compat_activity("query")["method"], "compat_activity")
            self.assertEqual(controller.compat_append_message({})["method"], "compat_append_message")
            self.assertEqual(controller.compat_update_runtime({})["method"], "compat_update_runtime")
            self.assertEqual(controller.compat_stop_agent({})["method"], "compat_stop_agent")
            self.assertEqual(controller._require_active().session()["team_id"], "alpha")
            self.assertIsNone(controller._team_for_file(None))
            self.assertEqual(controller._team_for_file(team_file.resolve())["team_id"], "alpha")
            self.assertEqual(controller._summary_text(""), "Untitled conversation")
            self.assertTrue(controller._summary_text("x" * 90).endswith("..."))

            controller._active = None
            self.assertEqual(controller.health().started_at, "now")
            self.assertIsNone(controller.session()["team_id"])
            self.assertEqual(controller.conversations(2)["conversations"], [])
            self.assertEqual(controller.workspace_files(query="", limit=1)["files"][0]["path"], "team.yaml")

            with self.assertRaises(StudioApiError):
                controller._require_active()
            with self.assertRaises(StudioApiError):
                controller.create_conversation(ConversationCreateRequest(team_id="alpha", initial_message=" "))
            with self.assertRaises(StudioApiError):
                controller._activate_team("alpha", " ")
            with self.assertRaises(StudioApiError):
                controller._activate_team("missing", "thread")

            controller._instances = {"alpha": SimpleNamespace(conversation_for=lambda _conversation_id: None)}
            with self.assertRaises(StudioApiError):
                controller._activate_team("alpha", "thread")

            controller._discovery = {"status": "blocked", "duplicate_ids": []}
            with self.assertRaises(StudioApiError):
                controller._ensure_discovery_ready()
            self.assertEqual(controller._persisted_conversations(10), [])

    def test_session_controller_sqlite_path_branches_resolve_from_workspace(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            controller = object.__new__(StudioSessionController)
            controller._workspace_dir = root
            controller._configuration = RuntimeConfiguration({"BACKEND": "sqlite", "SQLITE_PATH": "configured.sqlite"})
            controller._yaml_parser = YamlParser()

            self.assertIsNone(controller._sqlite_path_for_team({}))
            list_file = root / "list.yaml"
            list_file.write_text("- one\n", encoding="utf-8")
            self.assertIsNone(controller._sqlite_path_for_team({"team_file": str(list_file)}))
            memory_file = root / "memory.yaml"
            memory_file.write_text("schema_version: 1\ndefaults:\n  checkpointer:\n    default: memory\n", encoding="utf-8")
            self.assertIsNone(controller._sqlite_path_for_team({"team_file": str(memory_file)}))

            absolute = root / "absolute.sqlite"
            absolute_file = root / "absolute.yaml"
            absolute_file.write_text(
                f"defaults:\n  checkpointer:\n    default: sqlite\n    sqlite_path:\n      default: {absolute}\n",
                encoding="utf-8",
            )
            self.assertEqual(controller._sqlite_path_for_team({"team_file": str(absolute_file)}), absolute)

            configured_file = root / "configured.yaml"
            configured_file.write_text(
                "\n".join(
                    [
                        "working_directory: project",
                        "defaults:",
                        "  checkpointer:",
                        "    env: BACKEND",
                        "    default: memory",
                        "    sqlite_path:",
                        "      env: SQLITE_PATH",
                        "      default: ignored.sqlite",
                    ]
                ),
                encoding="utf-8",
            )
            self.assertEqual(
                controller._sqlite_path_for_team({"team_file": str(configured_file)}),
                (root / "configured.sqlite").resolve(),
            )
            self.assertEqual(controller._sqlite_conversations({"team_id": "alpha"}, root / "missing.sqlite", 10), [])
            empty_db = root / "empty.sqlite"
            sqlite3.connect(empty_db).close()
            self.assertEqual(controller._sqlite_conversations({"team_id": "alpha"}, empty_db, 10), [])

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

    def _write_discovery_team(
        self,
        path: Path,
        team_id: str,
        *,
        conversation: bool = True,
        working_directory: str | None = None,
    ) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        conversation_section = "conversation:\n  human_input:\n    default_targets: []" if conversation else ""
        working_directory_section = f"working_directory: {working_directory}" if working_directory else ""
        path.write_text(
            "\n".join(
                [
                    "schema_version: 1",
                    f"id: {team_id}",
                    "description: Test team",
                    working_directory_section,
                    "defaults:",
                    "  checkpointer:",
                    "    default: sqlite",
                    "    sqlite_path:",
                    "      default: .team-instanciator/checkpoints.sqlite",
                    conversation_section,
                    "agents:",
                    "  guide:",
                    "    kind: deepagent",
                    "    config: ./agents/guide.mdc",
                    "    entrypoint: true",
                    "    conversation:",
                    "      aliases:",
                    "        - mentor",
                    "  reviewer:",
                    "    kind: deepagent",
                    "    config: ./agents/reviewer.mdc",
                    "    conversation: {}",
                    "  helper:",
                    "    kind: subagent",
                    "    config: ./agents/helper.mdc",
                    "",
                ]
            ),
            encoding="utf-8",
        )

    def _fake_created_conversation(self, *, team_id: str, conversation_id: str, root_dir: Path):
        replay_events: list[ConversationEvent] = []

        def state():
            return {
                "team_id": team_id,
                "conversation_id": conversation_id,
                "participants": ["agent"],
                "runtime": {
                    "team_id": team_id,
                    "conversation_id": conversation_id,
                    "mention_hook_enabled": True,
                    "max_cascade_turns": None,
                },
                "events": [event.to_dict() for event in replay_events],
                "agent_states": [],
                "deliveries": [],
                "runs": [],
                "thread_frontiers": [],
                "control_events": [],
                "activities": [],
                "activity": None,
            }

        def append_human_message(content, *, author_id, files, wait, metadata=None):
            message_files = []
            for file in files or ():
                if isinstance(file, Path):
                    file_id = f"file_{len(replay_events) + len(message_files) + 1:02d}"
                    message_files.append(
                        ConversationFileRef(
                            id=file_id,
                            filename=file.name,
                            uri=f"conversation://files/{file_id}",
                            media_type=None,
                            size_bytes=file.stat().st_size,
                            added_by=author_id,
                        )
                    )
                else:
                    message_files.append(file)
            event = ConversationEvent(
                id=f"event_{len(replay_events) + 1:02d}",
                team_id=team_id,
                conversation_id=conversation_id,
                branch_id="branch_main",
                seq=len(replay_events) + 1,
                created_at="2026-06-01T10:00:01Z",
                author_id=author_id,
                author_kind="human",
                content=content,
                mentions=(),
                attachments=tuple(message_files),
                metadata=dict(metadata or {}),
            )
            replay_events.append(event)
            return SimpleNamespace(event=event, deliveries=(), failures=())

        return SimpleNamespace(
            checkpointer_handle=SimpleNamespace(connection=None),
            root_dir=root_dir,
            state=state,
            activity=lambda _agent_id=None: state(),
            append_human_message=append_human_message,
            runtime=SimpleNamespace(),
        )

    def _write_conversation_history(self, path: Path, *, team_id: str, conversation_id: str, content: str) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(path)
        try:
            connection.execute(
                """
                create table team_conversation_events (
                    team_id text not null,
                    conversation_id text not null,
                    seq integer not null,
                    created_at text not null,
                    author_id text not null,
                    author_kind text not null,
                    content text not null
                )
                """
            )
            connection.execute(
                """
                insert into team_conversation_events (
                    team_id,
                    conversation_id,
                    seq,
                    created_at,
                    author_id,
                    author_kind,
                    content
                ) values (?, ?, ?, ?, ?, ?, ?)
                """,
                (team_id, conversation_id, 1, "2026-06-01T10:00:00Z", "human", "human", content),
            )
            connection.commit()
        finally:
            connection.close()

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
        runs: list[dict[str, object]] | None = None,
        thread_frontiers: list[dict[str, object]] | None = None,
    ):
        messages = []
        injected_prompts = []
        stopped = []
        cancelled = []
        cleared = []
        control_events: list[dict[str, object]] = []
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
                "frontier_before_event_id": "frontier_event_01_before",
                "frontier_after_event_id": "frontier_event_01_after",
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
                "runs": list(runs or []),
                "model_attempts": [],
                "thread_frontiers": list(thread_frontiers or []),
                "control_events": list(control_events),
                "activities": [],
                "activity": None,
            }

        def activity(agent_id=None):
            snapshot = state()
            branch_id = branch_store.current_branch_id() if branch_store is not None else "branch_main"
            snapshot["private_thread_id"] = f"thread:branch:{branch_id}:mention:{agent_id}"
            snapshot["private_messages"] = [{"type": "ai", "name": agent_id, "content": "working", "tool_calls": []}]
            return snapshot

        def append_human_message(content, *, author_id, files, wait, metadata=None):
            message_files = []
            for file in files or ():
                if isinstance(file, Path):
                    file_id = f"file_{len(messages) + len(message_files) + 1}"
                    message_files.append(
                        ConversationFileRef(
                            id=file_id,
                            filename=file.name,
                            uri=f"conversation://files/{file_id}",
                            media_type=None,
                            size_bytes=file.stat().st_size,
                            added_by=author_id,
                        )
                    )
                else:
                    message_files.append(file)
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
                origin_checkpoint_id="frontier_event_01_before",
                origin_event_id=event_id,
                origin_logical_message_id="event_01",
                origin_previous_event_id=None,
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
                frontier_before_event_id="frontier_event_01_before",
                frontier_after_event_id=f"frontier_event_edit_{len(replay_events) + 1}_after",
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

        def inject_agent_prompt(agent_id, content, *, wait=False):
            injected_prompts.append((agent_id, content, wait))
            branch_id = branch_store.current_branch_id() if branch_store is not None else "branch_main"
            control_events.append(
                {
                    "id": f"ctrl_{len(control_events) + 1:02d}",
                    "team_id": "team",
                    "conversation_id": "thread",
                    "branch_id": branch_id,
                    "logical_thread_key": f"thread:mention:{agent_id}",
                    "physical_thread_id": f"thread:branch:{branch_id}:mention:{agent_id}",
                    "parent_run_id": "run_01",
                    "kind": "prompt-injection",
                    "content": content,
                    "created_at": "2026-06-01T10:00:06Z",
                }
            )
            event = ConversationEvent(
                id=f"event_injected_{len(replay_events) + 1}",
                team_id="team",
                conversation_id="thread",
                branch_id=branch_id,
                seq=len(replay_events) + 2,
                created_at="2026-06-01T10:00:07Z",
                author_id=agent_id,
                author_kind="agent",
                content="injected reply",
                mentions=(),
                source_thread_id=f"thread:branch:{branch_id}:mention:{agent_id}",
                source_message_id="message_injected",
                metadata={"control_event": "prompt-injection"},
            )
            replay_events.append(event)
            return SimpleNamespace(
                event=event,
                deliveries=(
                    SimpleNamespace(
                        to_dict=lambda: {
                            "id": "delivery_injected",
                            "team_id": "team",
                            "conversation_id": "thread",
                            "branch_id": branch_id,
                            "agent_id": agent_id,
                            "run_id": "run_injected",
                            "snapshot_seq": event.seq,
                            "status": "success",
                            "created_at": "2026-06-01T10:00:07Z",
                            "completed_at": "2026-06-01T10:00:08Z",
                            "error": None,
                        }
                    ),
                ),
                failures=(),
            )

        def cancel_queued_agent(agent_id, *, branch_id=None):
            cancelled.append((agent_id, branch_id or "branch_main"))
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
            origin_logical_message_id=None,
            origin_previous_event_id=None,
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
                origin_logical_message_id=origin_logical_message_id,
                origin_previous_event_id=origin_previous_event_id,
                origin_event_seq=origin_event_seq,
                head_checkpoint_id=head_checkpoint_id,
                parent_branch_id=parent_branch_id,
            )

        def list_branches(*, include_archived=False):
            if branch_store is None:
                raise AssertionError("branching is not enabled for this fake conversation")
            return branch_store.list_branches(include_archived=include_archived)

        def current_branch_id():
            if branch_store is None:
                raise AssertionError("branching is not enabled for this fake conversation")
            return branch_store.current_branch_id()

        def switch_branch(branch_id):
            if branch_store is None:
                raise AssertionError("branching is not enabled for this fake conversation")
            return branch_store.switch_branch(branch_id)

        def archive_branch(branch_id):
            if branch_store is None:
                raise AssertionError("branching is not enabled for this fake conversation")
            return branch_store.archive_branch(branch_id)

        def get_studio_branch_ui_state(*, participant_id="human", branch_id=None):
            if branch_store is None:
                raise AssertionError("branching is not enabled for this fake conversation")
            return branch_store.get_studio_branch_ui_state(
                participant_id=participant_id,
                branch_id=branch_id,
            ).to_dict()

        def save_studio_branch_ui_state(
            *,
            participant_id="human",
            branch_id=None,
            draft_content="",
            outbox_state=None,
            editing_event_id=None,
            selected_agent_id=None,
            scroll_anchor_event_id=None,
        ):
            if branch_store is None:
                raise AssertionError("branching is not enabled for this fake conversation")
            return branch_store.save_studio_branch_ui_state(
                participant_id=participant_id,
                branch_id=branch_id,
                draft_content=draft_content,
                outbox_state=outbox_state,
                editing_event_id=editing_event_id,
                selected_agent_id=selected_agent_id,
                scroll_anchor_event_id=scroll_anchor_event_id,
            ).to_dict()

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
                origin_logical_message_id=origin_event_id,
                origin_previous_event_id=None,
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
            "inject_agent_prompt": inject_agent_prompt,
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
                    "archive_branch": archive_branch,
                    "get_studio_branch_ui_state": get_studio_branch_ui_state,
                    "save_studio_branch_ui_state": save_studio_branch_ui_state,
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
        fake.injected_prompts = injected_prompts
        fake.stopped = stopped
        fake.cancelled = cancelled
        fake.cleared = cleared
        fake.runtime_calls = runtime_calls
        return fake


if __name__ == "__main__":
    unittest.main()
