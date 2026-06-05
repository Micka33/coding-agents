from __future__ import annotations

import importlib.metadata
import hashlib
import subprocess
from collections.abc import Mapping
from pathlib import Path
from typing import Any
from urllib.parse import urlencode

from src.team_instanciator.conversation.conversation_branch import ConversationBranch
from src.team_instanciator.conversation.conversation_interrupt import ConversationInterrupt
from src.team_instanciator.conversation.payloads import ConversationStateDict
from src.webapp.api.conversation_api_controller import ConversationApiController
from src.webapp.api.conversation_protocol import WebConversation
from src.webapp_studio.backend.api.checkpoint_history_reader import CheckpointHistoryReader
from src.webapp_studio.backend.api.studio_attachment_ref_factory import StudioAttachmentRefFactory
from src.webapp_studio.backend.api.studio_file_resource import StudioFileResource
from src.webapp_studio.backend.api.studio_api_error import StudioApiError
from src.webapp_studio.backend.api.studio_state_factory import StudioStateFactory
from src.webapp_studio.backend.api.studio_terminal_session import StudioTerminalSession
from src.webapp_studio.backend.api.time_utils import utc_now_iso
from src.webapp_studio.backend.contracts.agent_prompt_inject_request import AgentPromptInjectRequest
from src.webapp_studio.backend.contracts.append_message_request import AppendMessageRequest
from src.webapp_studio.backend.contracts.append_message_result import AppendMessageResult
from src.webapp_studio.backend.contracts.branch_create_request import BranchCreateRequest
from src.webapp_studio.backend.contracts.branch_summary import BranchSummary
from src.webapp_studio.backend.contracts.checkpoint_resume_request import CheckpointResumeRequest
from src.webapp_studio.backend.contracts.checkpoint_summary import CheckpointSummary
from src.webapp_studio.backend.contracts.conversation_delivery_dto import ConversationDeliveryDto
from src.webapp_studio.backend.contracts.edit_message_request import EditMessageRequest
from src.webapp_studio.backend.contracts.health_status import HealthStatus
from src.webapp_studio.backend.contracts.interrupt_request import InterruptRequest
from src.webapp_studio.backend.contracts.interrupt_resume_request import InterruptResumeRequest
from src.webapp_studio.backend.contracts.queue_clear_request import QueueClearRequest
from src.webapp_studio.backend.contracts.queue_item import QueueItem
from src.webapp_studio.backend.contracts.run_join_result import RunJoinResult
from src.webapp_studio.backend.contracts.run_summary import RunSummary
from src.webapp_studio.backend.contracts.runtime_update_request import RuntimeUpdateRequest
from src.webapp_studio.backend.contracts.studio_branch_ui_state_dto import StudioBranchUiStateDto
from src.webapp_studio.backend.contracts.studio_branch_ui_state_update_request import StudioBranchUiStateUpdateRequest
from src.webapp_studio.backend.contracts.studio_capabilities import StudioCapabilities
from src.webapp_studio.backend.contracts.studio_state import StudioState
from src.webapp_studio.backend.streaming.stream_buffer import StreamBuffer

_BLOCKED_FILE_MEDIA_TYPES = {"application/javascript", "image/svg+xml", "text/html", "text/javascript"}
_BLOCKED_FILE_SUFFIXES = {".htm", ".html", ".js", ".mjs", ".svg"}


class StudioApiController:
    def __init__(self, conversation: WebConversation, *, stream_buffer: StreamBuffer | None = None) -> None:
        self._conversation = conversation
        self._compat = ConversationApiController(conversation)
        self._attachment_factory = StudioAttachmentRefFactory(conversation)
        self._checkpoint_history_reader = CheckpointHistoryReader()
        self._state_factory = StudioStateFactory()
        self._stream_buffer = stream_buffer or StreamBuffer()
        self._started_at = utc_now_iso()
        self._dismissed_failed_queue_delivery_ids: set[str] = set()
        self._terminal_sessions: dict[str, StudioTerminalSession] = {}

    @property
    def stream_buffer(self) -> StreamBuffer:
        return self._stream_buffer

    def capabilities(self) -> StudioCapabilities:
        return StudioCapabilities(
            queue_control="available" if self._has_runtime_methods("cancel_queued_agent", "clear_queue") else "degraded",
            checkpoints="available" if self._checkpoint_storage_available() else "degraded",
            branching=(
                "available"
                if self._has_runtime_methods("create_branch", "list_branches", "current_branch_id", "switch_branch")
                else "degraded"
            ),
            time_travel="available" if self._has_runtime_methods("resume_checkpoint") else "degraded",
        )

    def health(self) -> HealthStatus:
        return HealthStatus(
            started_at=self._started_at,
            versions={
                "fastapi": self._version("fastapi"),
                "pydantic": self._version("pydantic"),
            },
        )

    def state(self) -> StudioState:
        state = self._compat.state()
        return self._studio_state_from_legacy(
            state,
            private_activity_states=self._private_activity_states(state),
        )

    def activity(self, agent_id: str | None = None) -> StudioState:
        query = "" if agent_id is None else urlencode({"agent_id": agent_id})
        return self._studio_state_from_legacy(self._compat.activity(query))

    def append_message(self, request: AppendMessageRequest) -> AppendMessageResult:
        if request.client_message_id:
            duplicate = self._event_for_client_message_id(request.client_message_id, request.author_id)
            if duplicate is not None:
                return AppendMessageResult(event=duplicate, deliveries=[], failures=[])

        files = self._attachment_factory.refs(request.attachments, author_id=request.author_id)
        metadata = {"client_message_id": request.client_message_id} if request.client_message_id else None
        try:
            appended = self._conversation.append_human_message(
                request.content,
                author_id=request.author_id,
                files=files,
                metadata=metadata,
                wait=request.wait,
            )
        except TypeError:
            appended = self._conversation.append_human_message(
                request.content,
                author_id=request.author_id,
                files=files,
                wait=request.wait,
            )
        result = AppendMessageResult(
            event=appended.event.to_dict(),
            deliveries=[delivery.to_dict() for delivery in appended.deliveries],
            failures=[delivery.to_dict() for delivery in appended.failures],
        )
        self._stream_buffer.publish("conversation.event.appended", result.event.model_dump(mode="json"))
        for delivery in result.deliveries + result.failures:
            self._publish_delivery_state(delivery)
        self._publish_queue_state(self.state())
        return result

    def edit_message(self, message_id: str, request: EditMessageRequest) -> StudioState:
        edit_message = self._runtime_method("edit_human_message")
        if edit_message is None:
            raise self._unsupported("branching", "Message editing is not supported by this runtime.")
        try:
            edited = edit_message(
                message_id,
                request.content,
                author_id=request.author_id,
                wait=request.wait,
            )
        except ValueError as error:
            raise StudioApiError(
                status_code=400,
                code="invalid_request",
                message=str(error),
                field="message_id",
            ) from error
        state = self.state()
        self._stream_buffer.publish("conversation.event.appended", edited.event.to_dict())
        for delivery in edited.deliveries + edited.failures:
            self._publish_delivery_state(ConversationDeliveryDto.model_validate(delivery.to_dict()))
        branch = self._branch_by_id(state.history.branches, state.history.current_branch_id)
        if branch is not None:
            self._stream_buffer.publish("branch.updated", branch.model_dump(mode="json"))
        self._stream_buffer.publish("snapshot.replace", state.model_dump(mode="json"))
        return state

    def session(self) -> dict[str, Any]:
        state = self._compat.state()
        checkpointer = self._checkpointer_context()
        return {
            "team_id": state["team_id"],
            "conversation_id": state["conversation_id"],
            "team_file": self._team_file(),
            "launcher_cwd": str(Path.cwd().resolve()),
            "resolved_root_dir": str(self._resolved_root_dir()),
            "checkpointer": checkpointer,
            "loaded_at": self._started_at,
        }

    def conversations(self, limit: int = 20) -> dict[str, Any]:
        state = self._compat.state()
        connection = self._sqlite_connection()
        team_id = str(state["team_id"])
        current_conversation_id = str(state["conversation_id"])
        if connection is None:
            return {
                "team_id": team_id,
                "current_conversation_id": current_conversation_id,
                "conversations": [
                    {
                        "conversation_id": current_conversation_id,
                        "event_count": len(state.get("events", [])),
                        "last_seq": max((int(event.get("seq") or 0) for event in state.get("events", [])), default=0),
                        "last_event_at": max((str(event.get("created_at") or "") for event in state.get("events", [])), default=None),
                        "last_author_id": str(state.get("events", [])[-1].get("author_id")) if state.get("events") else None,
                    }
                ],
            }
        rows = connection.execute(
            """
            select
                conversation_id,
                count(*) as event_count,
                max(seq) as last_seq,
                max(created_at) as last_event_at
            from team_conversation_events
            where team_id = ?
            group by conversation_id
            order by last_event_at desc
            limit ?
            """,
            (team_id, max(1, min(limit, 100))),
        ).fetchall()
        conversations = []
        for conversation_id, event_count, last_seq, last_event_at in rows:
            last_author = connection.execute(
                """
                select author_id
                from team_conversation_events
                where team_id = ? and conversation_id = ? and seq = ?
                limit 1
                """,
                (team_id, conversation_id, last_seq),
            ).fetchone()
            conversations.append(
                {
                    "conversation_id": str(conversation_id),
                    "event_count": int(event_count),
                    "last_seq": int(last_seq or 0),
                    "last_event_at": str(last_event_at) if last_event_at is not None else None,
                    "last_author_id": str(last_author[0]) if last_author is not None else None,
                }
            )
        return {
            "team_id": team_id,
            "current_conversation_id": current_conversation_id,
            "conversations": conversations,
        }

    def switch_conversation(self, conversation_id: str) -> dict[str, Any]:
        if not conversation_id.strip():
            raise StudioApiError(status_code=400, code="invalid_request", message="conversation_id is required", field="conversation_id")
        switch = getattr(self._conversation, "with_conversation_id", None)
        if not callable(switch):
            raise self._unsupported("conversation_switching", "Conversation switching is not supported by this runtime.")
        self._conversation = switch(conversation_id.strip())
        self._compat = ConversationApiController(self._conversation)
        self._attachment_factory = StudioAttachmentRefFactory(self._conversation)
        state = self.state()
        payload = {
            "session": self.session(),
            "state": state.model_dump(mode="json"),
        }
        self._stream_buffer.publish("snapshot.replace", state.model_dump(mode="json"))
        return payload

    def files(self) -> dict[str, Any]:
        file_items = []
        for event in self._compat.state().get("events", []):
            if not isinstance(event, dict):
                continue
            for attachment in event.get("attachments", []):
                if not isinstance(attachment, dict):
                    continue
                file_id = str(attachment.get("id") or "")
                if not file_id:
                    continue
                filename = str(attachment.get("filename") or file_id)
                media_type = self._media_type(attachment.get("media_type"))
                preview_url = None if self._blocked_file_type(filename, media_type) else f"/api/studio/v1/files/{file_id}/preview"
                file_items.append(
                    {
                        "id": file_id,
                        "filename": filename,
                        "media_type": media_type,
                        "size_bytes": self._optional_int(attachment.get("size_bytes")),
                        "added_by": str(attachment.get("added_by")) if attachment.get("added_by") is not None else None,
                        "event_id": event.get("id"),
                        "event_seq": event.get("seq"),
                        "preview_url": preview_url,
                        "download_url": f"/api/studio/v1/files/{file_id}/download",
                    }
                )
        return {"files": file_items}

    def changes(self) -> dict[str, Any]:
        root_dir = self._resolved_root_dir()
        try:
            result = subprocess.run(
                ["git", "-C", str(root_dir), "status", "--porcelain=v1", "-z", "--untracked-files=all"],
                check=True,
                capture_output=True,
            )
        except (OSError, subprocess.CalledProcessError):
            return {"changes": [], "supported": False}
        return {"changes": self._changes_from_git_status(result.stdout), "supported": True}

    def change_diff(self, change_id: str) -> dict[str, Any]:
        change = self._change_by_id(change_id)
        if change is None:
            raise StudioApiError(status_code=404, code="not_found", message="change not found", field="change_id")
        root_dir = self._resolved_root_dir()
        path = str(change["path"])
        if change["status"] == "untracked":
            absolute_path = (root_dir / path).resolve()
            if not self._path_is_within_root(absolute_path, root_dir) or not absolute_path.is_file():
                diff = ""
            else:
                result = subprocess.run(
                    ["git", "-C", str(root_dir), "diff", "--no-index", "--", "/dev/null", str(absolute_path)],
                    capture_output=True,
                    text=True,
                )
                diff = result.stdout or result.stderr
        else:
            diff = self._git_diff_for_path(root_dir, path)
        return {"change_id": change_id, "path": path, "diff": diff}

    def create_terminal_session(self) -> dict[str, Any]:
        session = StudioTerminalSession(self._resolved_root_dir())
        self._terminal_sessions[session.session_id] = session
        return session.snapshot()

    def terminal_output(self, session_id: str, cursor: int = 0) -> dict[str, Any]:
        return self._terminal_session(session_id).output_after(max(0, cursor))

    def terminal_input(self, session_id: str, data: str) -> dict[str, Any]:
        return self._terminal_session(session_id).write(data)

    def terminal_resize(self, session_id: str, *, columns: int, rows: int) -> dict[str, Any]:
        return self._terminal_session(session_id).resize(columns=columns, rows=rows)

    def terminate_terminal_session(self, session_id: str) -> dict[str, Any]:
        session = self._terminal_session(session_id)
        snapshot = session.terminate()
        self._terminal_sessions.pop(session_id, None)
        return snapshot

    def update_runtime(self, request: RuntimeUpdateRequest) -> StudioState:
        body: dict[str, object] = {}
        if "mention_hook_enabled" in request.model_fields_set:
            body["mention_hook_enabled"] = request.mention_hook_enabled
        if "max_cascade_turns" in request.model_fields_set:
            body["max_cascade_turns"] = request.max_cascade_turns
        state = self._studio_state_from_legacy(self._compat.update_runtime(body))
        self._stream_buffer.publish("snapshot.replace", state.model_dump(mode="json"))
        return state

    def stop_agent(self, agent_id: str) -> StudioState:
        if not agent_id:
            raise StudioApiError(status_code=400, code="invalid_request", message="agent_id is required", field="agent_id")
        active_run = self._active_run_for_agent(agent_id)
        state = self._studio_state_from_legacy(self._compat.stop_agent({"agent_id": agent_id}))
        self._stream_buffer.publish("agent.state.updated", {"agent_id": agent_id, "stop_requested": True})
        if active_run is not None:
            self._stream_buffer.publish(
                "run.updated",
                active_run.model_copy(
                    update={
                        "updated_at": utc_now_iso(),
                        "metadata": {
                            **active_run.metadata,
                            "stop_requested": True,
                        },
                    }
                ).model_dump(mode="json"),
            )
        self._stream_buffer.publish("snapshot.replace", state.model_dump(mode="json"))
        return state

    def inject_agent_prompt(self, agent_id: str, request: AgentPromptInjectRequest) -> StudioState:
        if not agent_id:
            raise StudioApiError(status_code=400, code="invalid_request", message="agent_id is required", field="agent_id")
        inject_agent_prompt = self._runtime_method("inject_agent_prompt")
        if inject_agent_prompt is None:
            raise self._unsupported("time_travel", f"Prompt injection is not supported for agent: {agent_id}")
        try:
            injected = inject_agent_prompt(agent_id, request.content, wait=request.wait)
        except ValueError as error:
            raise StudioApiError(
                status_code=400,
                code="invalid_request",
                message=str(error),
                field="content",
            ) from error
        state = self.state()
        self._stream_buffer.publish("conversation.event.appended", injected.event.to_dict())
        for delivery in injected.deliveries + injected.failures:
            self._publish_delivery_state(ConversationDeliveryDto.model_validate(delivery.to_dict()))
        self._stream_buffer.publish("snapshot.replace", state.model_dump(mode="json"))
        return state

    def runs(self) -> list[RunSummary]:
        return self.state().runs

    def join_run(self, run_id: str) -> RunJoinResult:
        if not any(run.id == run_id for run in self.runs()):
            raise StudioApiError(status_code=404, code="not_found", message="run not found", field="run_id")
        return RunJoinResult(
            run_id=run_id,
            cursor=self._stream_buffer.latest_cursor(),
            replay_available=True,
            stream_url=f"/api/studio/v1/stream?run_id={run_id}",
        )

    def queue(self) -> list[QueueItem]:
        return self.state().queue

    def cancel_queue_item(self, queue_item_id: str) -> list[QueueItem]:
        item = self._queue_item(queue_item_id)
        if not item.can_cancel:
            raise self._unsupported("queue_control", f"Queue item is not cancellable: {queue_item_id}")
        self._conversation.runtime.cancel_queued_agent(item.agent_id, branch_id=item.branch_id)
        state = self.state()
        self._publish_queue_state(state)
        return state.queue

    def clear_queue(self, request: QueueClearRequest) -> list[QueueItem]:
        if request.scope in {"failed", "all"}:
            self._dismissed_failed_queue_delivery_ids.update(
                item.id.removeprefix("queue_failed_")
                for item in self.state().queue
                if item.status == "failed" and item.id.startswith("queue_failed_")
            )
        self._conversation.runtime.clear_queue(request.scope)
        state = self.state()
        self._publish_queue_state(state)
        return state.queue

    def checkpoints(self) -> list[CheckpointSummary]:
        return self.state().history.checkpoints

    def checkpoint(self, checkpoint_id: str) -> CheckpointSummary:
        for checkpoint in self.checkpoints():
            if checkpoint.id == checkpoint_id:
                return checkpoint
        raise StudioApiError(status_code=404, code="not_found", message="checkpoint not found", field="checkpoint_id")

    def resume_checkpoint(self, checkpoint_id: str, request: CheckpointResumeRequest) -> StudioState:
        checkpoint = self.checkpoint(checkpoint_id)
        resume_checkpoint = self._runtime_method("resume_checkpoint")
        if resume_checkpoint is None:
            raise self._unsupported("time_travel", f"Checkpoint {request.mode} is not supported yet: {checkpoint_id}")
        if checkpoint.capabilities.resume != "available":
            raise self._unsupported("time_travel", f"Checkpoint {request.mode} is not available for: {checkpoint_id}")
        origin_event_id, origin_event_seq = self._checkpoint_origin(checkpoint)
        result = resume_checkpoint(
            checkpoint_id=checkpoint.id,
            checkpoint_ns=checkpoint.checkpoint_ns,
            thread_id=checkpoint.thread_id,
            mode=request.mode,
            edited_content=request.edited_content,
            origin_event_id=origin_event_id,
            origin_event_seq=origin_event_seq,
        )
        state = self.state()
        branch = self._branch_by_id(state.history.branches, str(result.branch.id))
        if branch is not None:
            self._stream_buffer.publish("branch.updated", branch.model_dump(mode="json"))
        self._stream_buffer.publish("conversation.event.appended", result.event.to_dict())
        self._stream_buffer.publish("snapshot.replace", state.model_dump(mode="json"))
        return state

    def branches(self) -> list[BranchSummary]:
        return self.state().history.branches

    def create_branch(self, request: BranchCreateRequest) -> BranchSummary:
        create_branch = self._runtime_method("create_branch")
        if create_branch is None:
            origin = request.checkpoint_id or request.message_id or "current"
            raise self._unsupported("branching", f"Branch creation is not supported yet from: {origin}")
        checkpoints = self.checkpoints()
        origin_checkpoint = self._origin_checkpoint(request, checkpoints)
        if origin_checkpoint is not None and origin_checkpoint.capabilities.branch_from_here != "available":
            raise self._unsupported(
                "branching",
                f"Branch creation is not available from checkpoint: {origin_checkpoint.id}",
            )
        origin_event_id, origin_event_seq = self._checkpoint_origin(origin_checkpoint) if origin_checkpoint is not None else (None, None)
        origin_logical_message_id, origin_previous_event_id = self._event_origin_metadata(origin_event_id)
        created = create_branch(
            label=request.label,
            origin_checkpoint_id=origin_checkpoint.id if origin_checkpoint is not None else None,
            origin_event_id=origin_event_id,
            origin_logical_message_id=origin_logical_message_id,
            origin_previous_event_id=origin_previous_event_id,
            origin_event_seq=origin_event_seq,
            head_checkpoint_id=origin_checkpoint.id if origin_checkpoint is not None else None,
            parent_branch_id=self._current_branch_id(),
        )
        state = self.state()
        branch = self._branch_by_id(state.history.branches, str(created.id))
        self._publish_branch_state(state, branch)
        return branch

    def switch_branch(self, branch_id: str) -> list[BranchSummary]:
        switch_branch = self._runtime_method("switch_branch")
        if switch_branch is None:
            if branch_id == "branch_main":
                return self.branches()
            raise self._unsupported("branching", f"Branch switching is not supported yet: {branch_id}")
        if self._branch_by_id(self.branches(), branch_id) is None:
            raise StudioApiError(status_code=404, code="not_found", message="branch not found", field="branch_id")
        switch_branch(branch_id)
        state = self.state()
        branch = self._branch_by_id(state.history.branches, branch_id)
        if branch is not None:
            self._publish_branch_state(state, branch)
        return state.history.branches

    def update_ui_state(self, request: StudioBranchUiStateUpdateRequest) -> StudioBranchUiStateDto:
        save_ui_state = self._runtime_method("save_studio_branch_ui_state")
        if save_ui_state is None:
            raise self._unsupported("ui_state", "Studio branch UI state is not supported by this runtime.")
        try:
            state = StudioBranchUiStateDto.model_validate(
                save_ui_state(
                    branch_id=request.branch_id,
                    participant_id=request.participant_id,
                    draft_content=request.draft_content,
                    outbox_state=request.outbox_state,
                    editing_event_id=request.editing_event_id,
                    selected_agent_id=request.selected_agent_id,
                    scroll_anchor_event_id=request.scroll_anchor_event_id,
                )
            )
        except ValueError as error:
            raise StudioApiError(
                status_code=400,
                code="invalid_request",
                message=str(error),
                field="ui_state",
            ) from error
        self._stream_buffer.publish("studio.ui_state.updated", state.model_dump(mode="json"))
        return state

    def interrupts(self) -> list[InterruptRequest]:
        return [self._interrupt_request(interrupt) for interrupt in self._interrupts_from_runtime()]

    def resume_interrupt(self, interrupt_id: str, request: InterruptResumeRequest) -> StudioState:
        resume_interrupt = self._runtime_method("resume_interrupt")
        if resume_interrupt is None:
            raise self._unsupported("interrupts", f"Interrupt {request.decision} is not supported yet: {interrupt_id}")
        resolved = resume_interrupt(
            interrupt_id,
            decision=request.decision,
            response=request.response,
            edited_payload=request.edited_payload,
        )
        if resolved is None:
            raise StudioApiError(status_code=404, code="not_found", message="interrupt not found", field="interrupt_id")
        state = self.state()
        self._stream_buffer.publish("interrupt.resolved", self._interrupt_request(resolved).model_dump(mode="json"))
        self._stream_buffer.publish("snapshot.replace", state.model_dump(mode="json"))
        return state


    def file_resource(self, file_id: str, *, allow_blocked: bool = False) -> StudioFileResource:
        if not file_id or "/" in file_id or "\\" in file_id or file_id in {".", ".."}:
            raise StudioApiError(status_code=404, code="not_found", message="file not found", field="file_id")
        state = self._compat.state()
        attachment = self._attachment(file_id, state)
        if attachment is None:
            raise StudioApiError(status_code=404, code="not_found", message="file not found", field="file_id")
        filename = str(attachment.get("filename") or file_id)
        media_type = self._media_type(attachment.get("media_type"))
        if not allow_blocked and self._blocked_file_type(filename, media_type):
            raise StudioApiError(
                status_code=415,
                code="unsupported_media_type",
                message="file media type is not served inline",
                field="file_id",
                details={"file_id": file_id, "media_type": media_type},
            )
        root_dir = getattr(self._conversation, "root_dir", None)
        if root_dir is None:
            raise StudioApiError(status_code=404, code="not_found", message="file not found", field="file_id")
        base_path = (
            Path(root_dir).expanduser().resolve()
            / ".coding-agents"
            / "conversations"
            / state["conversation_id"]
            / "files"
        ).resolve()
        path = (base_path / file_id).resolve()
        if path.parent != base_path or not path.is_file():
            raise StudioApiError(status_code=404, code="not_found", message="file not found", field="file_id")
        return StudioFileResource(path=path, filename=filename, media_type=media_type)

    def compat_state(self) -> ConversationStateDict:
        return self._compat.state()

    def compat_activity(self, query: str) -> ConversationStateDict:
        return self._compat.activity(query)

    def compat_append_message(self, body: dict[str, object]) -> dict[str, object]:
        result = AppendMessageResult.model_validate(self._compat.append_message(body))
        self._stream_buffer.publish("conversation.event.appended", result.event.model_dump(mode="json"))
        for delivery in result.deliveries + result.failures:
            self._publish_delivery_state(delivery)
        self._publish_queue_state(self.state())
        return result.model_dump(mode="json")

    def compat_update_runtime(self, body: dict[str, object]) -> ConversationStateDict:
        state = self._compat.update_runtime(body)
        self._stream_buffer.publish("snapshot.replace", self._studio_state_from_legacy(state).model_dump(mode="json"))
        return state

    def compat_stop_agent(self, body: dict[str, object]) -> ConversationStateDict:
        agent_id = str(body.get("agent_id") or "")
        self.stop_agent(agent_id)
        return self._compat.state()

    def _unsupported(self, capability: str, message: str) -> StudioApiError:
        return StudioApiError(
            status_code=501,
            code="unsupported_feature",
            message=message,
            retryable=False,
            details={"capability": capability},
        )

    def _queue_item(self, queue_item_id: str) -> QueueItem:
        for item in self.queue():
            if item.id == queue_item_id:
                return item
        raise StudioApiError(status_code=404, code="not_found", message="queue item not found", field="queue_item_id")

    def _publish_queue_state(self, state: StudioState) -> None:
        self._stream_buffer.publish("queue.updated", {"items": [item.model_dump(mode="json") for item in state.queue]})
        self._stream_buffer.publish("snapshot.replace", state.model_dump(mode="json"))

    def _publish_delivery_state(self, delivery: ConversationDeliveryDto) -> None:
        started = self._run_started_from_delivery(delivery)
        if started is not None:
            self._stream_buffer.publish("run.started", started.model_dump(mode="json"))
        self._stream_buffer.publish("conversation.delivery.updated", delivery.model_dump(mode="json"))
        run = self._run_from_delivery(delivery)
        if run is not None:
            self._stream_buffer.publish("run.completed", run.model_dump(mode="json"))

    def _run_started_from_delivery(self, delivery: ConversationDeliveryDto) -> RunSummary | None:
        if delivery.run_id is None:
            return None
        return RunSummary(
            id=delivery.run_id,
            conversation_id=delivery.conversation_id,
            agent_id=delivery.agent_id,
            status="running",
            created_at=delivery.created_at,
            updated_at=delivery.created_at,
            cursor=self._stream_buffer.latest_cursor(),
            metadata={
                "delivery_id": delivery.id,
                "branch_id": delivery.branch_id,
                "delivery_status": delivery.status,
                "snapshot_seq": delivery.snapshot_seq,
            },
        )

    def _run_from_delivery(self, delivery: ConversationDeliveryDto) -> RunSummary | None:
        if delivery.run_id is None:
            return None
        return RunSummary(
            id=delivery.run_id,
            conversation_id=delivery.conversation_id,
            agent_id=delivery.agent_id,
            status=self._run_status_from_delivery(delivery.status),
            created_at=delivery.created_at,
            updated_at=delivery.completed_at or delivery.created_at,
            completed_at=delivery.completed_at,
            cursor=self._stream_buffer.latest_cursor(),
            metadata={
                "delivery_id": delivery.id,
                "branch_id": delivery.branch_id,
                "delivery_status": delivery.status,
                "error": delivery.error,
                "snapshot_seq": delivery.snapshot_seq,
            },
        )

    def _run_status_from_delivery(self, status: str) -> str:
        if status in {"failed", "empty", "interrupted", "cascade-limited"}:
            return "failed"
        if status == "stopped":
            return "stopped"
        if status == "ignored":
            return "superseded"
        return "completed"

    def _active_run_for_agent(self, agent_id: str) -> RunSummary | None:
        for run in self.runs():
            if run.agent_id == agent_id and run.status in {"queued", "running"}:
                return run
        return None

    def _publish_branch_state(self, state: StudioState, branch: BranchSummary) -> None:
        self._stream_buffer.publish("branch.updated", branch.model_dump(mode="json"))
        self._stream_buffer.publish("snapshot.replace", state.model_dump(mode="json"))

    def _studio_state_from_legacy(
        self,
        state: ConversationStateDict,
        *,
        private_activity_states: list[ConversationStateDict] | None = None,
    ) -> StudioState:
        checkpoints = self._checkpoint_history_reader.checkpoints(self._conversation, state)
        current_branch_id = self._current_branch_id()
        return self._state_factory.from_legacy_state(
            state,
            checkpoints=self._checkpoint_capabilities(checkpoints, state, current_branch_id=current_branch_id),
            branches=self._branches_from_runtime(),
            interrupts=self._interrupts_from_runtime(),
            current_branch_id=current_branch_id,
            dismissed_failed_queue_delivery_ids=self._dismissed_failed_queue_delivery_ids,
            private_activity_states=private_activity_states,
            ui_state=self._studio_ui_state(current_branch_id=current_branch_id),
        )

    def _private_activity_states(self, state: ConversationStateDict) -> list[ConversationStateDict]:
        snapshots = []
        for participant in state.get("participants", []):
            agent_id = str(participant)
            if not agent_id:
                continue
            snapshots.append(self._compat.activity(urlencode({"agent_id": agent_id})))
        return snapshots

    def _checkpoint_capabilities(
        self,
        checkpoints: list[CheckpointSummary],
        state: ConversationStateDict,
        *,
        current_branch_id: str,
    ) -> list[CheckpointSummary]:
        can_branch = self._runtime_method("create_branch") is not None
        can_resume = self._runtime_method("resume_checkpoint") is not None
        if not can_branch and not can_resume:
            return checkpoints
        forkable_keys, continuable_keys, has_usability_metadata = self._checkpoint_usability(
            state,
            current_branch_id=current_branch_id,
        )
        updated = []
        for checkpoint in checkpoints:
            branch_from_here = checkpoint.capabilities.branch_from_here
            resume = checkpoint.capabilities.resume
            if can_branch:
                branch_from_here = (
                    "available"
                    if not has_usability_metadata or self._checkpoint_is_usable(checkpoint, forkable_keys)
                    else "unsupported"
                )
            if can_resume:
                resume = (
                    "available"
                    if not has_usability_metadata or self._checkpoint_is_usable(checkpoint, continuable_keys)
                    else "unsupported"
                )
            updated.append(
                checkpoint.model_copy(
                    update={
                        "capabilities": checkpoint.capabilities.model_copy(
                            update={
                                "branch_from_here": branch_from_here,
                                "resume": resume,
                            }
                        ),
                    }
                )
            )
        return updated

    def _checkpoint_usability(
        self,
        state: ConversationStateDict,
        *,
        current_branch_id: str,
    ) -> tuple[set[tuple[str | None, str]], set[tuple[str | None, str]], bool]:
        forkable: set[tuple[str | None, str]] = set()
        continuable: set[tuple[str | None, str]] = set()
        has_metadata = False
        for frontier in state.get("thread_frontiers", []):
            if not isinstance(frontier, Mapping):
                continue
            if self._state_branch_id(frontier) != current_branch_id:
                continue
            checkpoint_id = frontier.get("checkpoint_id")
            if checkpoint_id is None:
                continue
            has_metadata = True
            key = (self._optional_str(frontier.get("physical_thread_id")), str(checkpoint_id))
            if frontier.get("usable_for_fork"):
                forkable.add(key)
            if frontier.get("usable_for_continue"):
                continuable.add(key)

        for run in state.get("runs", []):
            if not isinstance(run, Mapping):
                continue
            if self._state_branch_id(run) != current_branch_id:
                continue
            if run.get("stable_checkpoint_id") is not None or run.get("latest_checkpoint_id") is not None:
                has_metadata = True
            if run.get("commit_state") != "committed" or run.get("stable_checkpoint_id") is None:
                continue
            key = (self._optional_str(run.get("physical_thread_id")), str(run["stable_checkpoint_id"]))
            if run.get("usable_for_fork"):
                forkable.add(key)
            if run.get("usable_for_continue"):
                continuable.add(key)
        return forkable, continuable, has_metadata

    def _checkpoint_is_usable(self, checkpoint: CheckpointSummary, usable_keys: set[tuple[str | None, str]]) -> bool:
        return (checkpoint.thread_id, checkpoint.id) in usable_keys or (None, checkpoint.id) in usable_keys

    def _state_branch_id(self, item: Mapping[str, object]) -> str:
        value = item.get("branch_id")
        return str(value) if value is not None else "branch_main"

    def _optional_str(self, value: object) -> str | None:
        return str(value) if value is not None else None

    def _origin_checkpoint(self, request: BranchCreateRequest, checkpoints: list[CheckpointSummary]) -> CheckpointSummary | None:
        if request.checkpoint_id is not None:
            return self.checkpoint(request.checkpoint_id)
        if request.message_id is not None:
            checkpoint = self._checkpoint_for_message(checkpoints, request.message_id)
            if checkpoint is not None:
                return checkpoint
            if self._conversation_event_exists(request.message_id):
                raise self._unsupported("branching", "Branch creation from this message requires a checkpoint.")
            raise StudioApiError(status_code=404, code="not_found", message="message not found", field="message_id")
        if checkpoints:
            return checkpoints[-1]
        raise self._unsupported("branching", "Branch creation from current state requires a checkpoint.")

    def _checkpoint_origin(self, checkpoint: CheckpointSummary) -> tuple[str | None, int | None]:
        event_id = checkpoint.summary.get("event_id")
        event_seq = checkpoint.summary.get("event_seq")
        return (
            str(event_id) if event_id else None,
            int(event_seq) if isinstance(event_seq, int) else None,
        )

    def _event_origin_metadata(self, event_id: str | None) -> tuple[str | None, str | None]:
        if event_id is None:
            return None, None
        event = next((item for item in self.state().conversation.events if item.id == event_id), None)
        if event is None:
            return None, None
        return event.logical_message_id, event.parent_event_id

    def _checkpoint_for_message(self, checkpoints: list[CheckpointSummary], message_id: str) -> CheckpointSummary | None:
        for checkpoint in reversed(checkpoints):
            if checkpoint.summary.get("event_id") == message_id:
                return checkpoint
        return None

    def _conversation_event_exists(self, message_id: str) -> bool:
        return any(event.get("id") == message_id for event in self._compat.state().get("events", []))

    def _branches_from_runtime(self) -> list[ConversationBranch]:
        list_branches = self._runtime_method("list_branches")
        if list_branches is None:
            return []
        return list(list_branches())

    def _current_branch_id(self) -> str:
        current_branch_id = self._runtime_method("current_branch_id")
        if current_branch_id is None:
            return "branch_main"
        return str(current_branch_id())

    def _studio_ui_state(self, *, current_branch_id: str) -> StudioBranchUiStateDto:
        get_ui_state = self._runtime_method("get_studio_branch_ui_state")
        if get_ui_state is None:
            legacy_state = self._compat.state()
            return StudioBranchUiStateDto(
                team_id=str(legacy_state["team_id"]),
                conversation_id=str(legacy_state["conversation_id"]),
                branch_id=current_branch_id,
                participant_id="human",
                updated_at=utc_now_iso(),
            )
        return StudioBranchUiStateDto.model_validate(
            get_ui_state(participant_id="human", branch_id=current_branch_id)
        )

    def _interrupts_from_runtime(self) -> list[ConversationInterrupt]:
        list_interrupts = self._runtime_method("list_interrupts")
        if list_interrupts is None:
            return []
        return list(list_interrupts())

    def _interrupt_request(self, interrupt: ConversationInterrupt) -> InterruptRequest:
        return InterruptRequest(
            id=interrupt.id,
            branch_id=interrupt.branch_id,
            run_id=interrupt.run_id,
            agent_id=interrupt.agent_id,
            checkpoint_id=interrupt.checkpoint_id,
            created_at=interrupt.created_at,
            kind=interrupt.kind,
            payload=interrupt.payload,
            status=interrupt.status,
            decisions=list(interrupt.decisions),
        )

    def _runtime_method(self, name: str):
        method = getattr(self._conversation.runtime, name, None)
        return method if callable(method) else None

    def _has_runtime_methods(self, *names: str) -> bool:
        return all(self._runtime_method(name) is not None for name in names)

    def _checkpoint_storage_available(self) -> bool:
        handle = getattr(self._conversation, "checkpointer_handle", None)
        return getattr(handle, "connection", None) is not None

    def _branch_by_id(self, branches: list[BranchSummary], branch_id: str) -> BranchSummary | None:
        for branch in branches:
            if branch.id == branch_id:
                return branch
        return None

    def _attachment(self, file_id: str, state: ConversationStateDict) -> dict[str, Any] | None:
        for event in state.get("events", []):
            for attachment in event.get("attachments", []):
                if isinstance(attachment, dict) and attachment.get("id") == file_id:
                    return attachment
        return None

    def _media_type(self, value: object) -> str | None:
        return str(value).split(";", maxsplit=1)[0].strip().lower() if value else None

    def _blocked_file_type(self, filename: str, media_type: str | None) -> bool:
        return (media_type in _BLOCKED_FILE_MEDIA_TYPES) or Path(filename).suffix.lower() in _BLOCKED_FILE_SUFFIXES

    def _changes_from_git_status(self, output: bytes) -> list[dict[str, Any]]:
        records = [record for record in output.split(b"\0") if record]
        changes: list[dict[str, Any]] = []
        index = 0
        while index < len(records):
            record = records[index].decode("utf-8", errors="replace")
            if len(record) < 4:
                index += 1
                continue
            code = record[:2]
            path = record[3:]
            source_path = None
            if code[0] in {"R", "C"} or code[1] in {"R", "C"}:
                index += 1
                if index < len(records):
                    source_path = records[index].decode("utf-8", errors="replace")
            change_id = self._change_id(path)
            changes.append(
                {
                    "id": change_id,
                    "path": path,
                    "status": self._change_status(code),
                    "source": "git",
                    "agent_id": None,
                    "event_id": None,
                    "diff_url": f"/api/studio/v1/changes/{change_id}/diff",
                    "source_path": source_path,
                }
            )
            index += 1
        return changes

    def _change_id(self, path: str) -> str:
        digest = hashlib.sha256(path.encode("utf-8", errors="replace")).hexdigest()[:16]
        return f"git_{digest}"

    def _change_status(self, code: str) -> str:
        if code == "??":
            return "untracked"
        if "D" in code:
            return "deleted"
        if "R" in code:
            return "renamed"
        if "C" in code:
            return "copied"
        if "A" in code:
            return "added"
        if "M" in code:
            return "modified"
        return "changed"

    def _change_by_id(self, change_id: str) -> dict[str, Any] | None:
        for change in self.changes()["changes"]:
            if change["id"] == change_id:
                return change
        return None

    def _git_diff_for_path(self, root_dir: Path, path: str) -> str:
        absolute_path = (root_dir / path).resolve()
        if not self._path_is_within_root(absolute_path, root_dir):
            raise StudioApiError(status_code=404, code="not_found", message="change not found", field="change_id")
        commands = [
            ["git", "-C", str(root_dir), "diff", "--", path],
            ["git", "-C", str(root_dir), "diff", "--cached", "--", path],
        ]
        outputs = []
        for command in commands:
            result = subprocess.run(command, capture_output=True, text=True)
            if result.stdout:
                outputs.append(result.stdout)
        return "\n".join(outputs)

    def _path_is_within_root(self, path: Path, root_dir: Path) -> bool:
        try:
            path.relative_to(root_dir.resolve())
        except ValueError:
            return False
        return True

    def _terminal_session(self, session_id: str) -> StudioTerminalSession:
        session = self._terminal_sessions.get(session_id)
        if session is None:
            raise StudioApiError(status_code=404, code="not_found", message="terminal session not found", field="session_id")
        return session

    def _event_for_client_message_id(self, client_message_id: str, author_id: str) -> dict[str, Any] | None:
        for event in self._compat.state().get("events", []):
            if not isinstance(event, dict):
                continue
            metadata = event.get("metadata")
            if not isinstance(metadata, Mapping):
                continue
            if metadata.get("client_message_id") == client_message_id and event.get("author_id") == author_id:
                return event
        return None

    def _team_file(self) -> str | None:
        team = getattr(self._conversation, "team", None)
        path = getattr(team, "path", None)
        if path is None:
            return None
        return str(Path(path).expanduser().resolve())

    def _resolved_root_dir(self) -> Path:
        root_dir = getattr(self._conversation, "root_dir", None)
        if root_dir is None:
            return Path.cwd().resolve()
        return Path(root_dir).expanduser().resolve()

    def _checkpointer_context(self) -> dict[str, Any]:
        connection = self._sqlite_connection()
        sqlite_path = self._sqlite_database_path(connection) if connection is not None else None
        backend = "sqlite" if sqlite_path is not None else "memory"
        storage_id = f"sqlite:{sqlite_path}" if sqlite_path is not None else f"memory:{self._compat.state()['team_id']}:{self._compat.state()['conversation_id']}"
        return {
            "backend": backend,
            "sqlite_path": sqlite_path,
            "storage_id": storage_id,
        }

    def _sqlite_connection(self):
        handle = getattr(self._conversation, "checkpointer_handle", None)
        return getattr(handle, "connection", None)

    def _sqlite_database_path(self, connection: Any) -> str | None:
        try:
            rows = connection.execute("pragma database_list").fetchall()
        except Exception:
            return None
        for row in rows:
            if len(row) >= 3 and row[1] == "main" and row[2]:
                return str(Path(str(row[2])).expanduser().resolve())
        return None

    def _optional_int(self, value: object) -> int | None:
        if isinstance(value, int):
            return value
        if isinstance(value, str) and value.isdigit():
            return int(value)
        return None

    def _version(self, package: str) -> str:
        try:
            return importlib.metadata.version(package)
        except importlib.metadata.PackageNotFoundError:
            return "unknown"
