from __future__ import annotations

import argparse
import asyncio
from contextlib import suppress
from collections.abc import AsyncIterator
from typing import Any

from fastapi import FastAPI, Request
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from pydantic import ValidationError

from src.team_instanciator.interfaces.cli_support import build_config_variables, parse_key_value_pairs
from src.webapp.api.conversation_protocol import WebConversation
from src.webapp_studio.backend.api.studio_api_controller import StudioApiController
from src.webapp_studio.backend.api.studio_api_error import StudioApiError
from src.webapp_studio.backend.api.studio_session_controller import StudioSessionController
from src.webapp_studio.backend.contracts.agent_prompt_inject_request import AgentPromptInjectRequest
from src.webapp_studio.backend.contracts.append_message_request import AppendMessageRequest
from src.webapp_studio.backend.contracts.branch_create_request import BranchCreateRequest
from src.webapp_studio.backend.contracts.checkpoint_resume_request import CheckpointResumeRequest
from src.webapp_studio.backend.contracts.conversation_create_request import ConversationCreateRequest
from src.webapp_studio.backend.contracts.edit_message_request import EditMessageRequest
from src.webapp_studio.backend.contracts.interrupt_resume_request import InterruptResumeRequest
from src.webapp_studio.backend.contracts.queue_clear_request import QueueClearRequest
from src.webapp_studio.backend.contracts.runtime_update_request import RuntimeUpdateRequest
from src.webapp_studio.backend.contracts.studio_branch_ui_state_update_request import StudioBranchUiStateUpdateRequest
from src.webapp_studio.backend.contracts.studio_capabilities import StudioCapabilities
from src.webapp_studio.backend.contracts.studio_envelope import StudioEnvelope
from src.webapp_studio.backend.contracts.studio_error import StudioError
from src.webapp_studio.backend.streaming.stream_buffer import StreamBuffer
from src.webapp_studio.backend.streaming.stream_client_queue import StreamClientQueue

CONTENT_SECURITY_POLICY = (
    "default-src 'self'; "
    "connect-src 'self' blob: http://127.0.0.1:* http://localhost:*; "
    "img-src 'self' data: blob:; "
    "style-src 'self' 'unsafe-inline'; "
    "script-src 'self'; "
    "frame-src 'self' http://127.0.0.1:* http://localhost:*; "
    "base-uri 'none'; "
    "object-src 'none'"
)


def create_app(conversation: WebConversation | StudioSessionController, *, stream_buffer: StreamBuffer | None = None) -> FastAPI:
    app = FastAPI(title="Webapp Studio Backend", version="studio.v1")
    controller = (
        conversation
        if isinstance(conversation, StudioSessionController)
        else StudioApiController(conversation, stream_buffer=stream_buffer)
    )

    def ok(data: Any) -> JSONResponse:
        return _ok(data, capabilities=controller.capabilities())

    def error_response(status_code: int, error: StudioError) -> JSONResponse:
        return _error_response(status_code, error, capabilities=controller.capabilities())

    @app.middleware("http")
    async def security_headers(request: Request, call_next: Any) -> Any:
        response = await call_next(request)
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("Referrer-Policy", "no-referrer")
        response.headers.setdefault("Content-Security-Policy", CONTENT_SECURITY_POLICY)
        return response

    @app.exception_handler(StudioApiError)
    async def studio_api_error_handler(_request: Request, error: StudioApiError) -> JSONResponse:
        return error_response(
            error.status_code,
            StudioError(
                code=error.code,
                message=error.message,
                field=error.field,
                retryable=error.retryable,
                details=error.details,
            ),
        )

    @app.exception_handler(ValueError)
    async def value_error_handler(_request: Request, error: ValueError) -> JSONResponse:
        return error_response(400, StudioError(code="invalid_request", message=str(error), retryable=False))

    @app.exception_handler(ValidationError)
    async def validation_error_handler(_request: Request, error: ValidationError) -> JSONResponse:
        return error_response(
            422,
            StudioError(
                code="invalid_request",
                message="Request validation failed.",
                retryable=False,
                details={"errors": error.errors()},
            ),
        )

    @app.exception_handler(RequestValidationError)
    async def request_validation_error_handler(_request: Request, error: RequestValidationError) -> JSONResponse:
        return error_response(
            422,
            StudioError(
                code="invalid_request",
                message="Request validation failed.",
                retryable=False,
                details={"errors": error.errors()},
            ),
        )

    @app.get("/health")
    async def root_health() -> JSONResponse:
        return ok(controller.health())

    @app.get("/api/studio/v1/health")
    async def health() -> JSONResponse:
        return ok(controller.health())

    @app.get("/api/studio/v1/state")
    async def state() -> JSONResponse:
        return ok(controller.state())

    @app.get("/api/studio/v1/session")
    async def session() -> JSONResponse:
        return ok(controller.session())

    @app.get("/api/studio/v1/teams")
    async def teams() -> JSONResponse:
        return ok(controller.teams())

    @app.get("/api/studio/v1/conversations")
    async def conversations(limit: int = 20) -> JSONResponse:
        return ok(controller.conversations(limit))

    @app.post("/api/studio/v1/conversations")
    async def create_conversation(request: ConversationCreateRequest) -> JSONResponse:
        return ok(controller.create_conversation(request))

    @app.put("/api/studio/v1/session/conversation")
    async def switch_conversation(body: dict[str, Any]) -> JSONResponse:
        team_id = body.get("team_id")
        return ok(controller.switch_conversation(str(body.get("conversation_id") or ""), str(team_id) if team_id is not None else None))

    @app.get("/api/studio/v1/activity")
    async def activity(agent_id: str | None = None) -> JSONResponse:
        return ok(controller.activity(agent_id))

    @app.post("/api/studio/v1/messages")
    async def append_message(request: AppendMessageRequest) -> JSONResponse:
        return ok(controller.append_message(request))

    @app.post("/api/studio/v1/messages/{message_id}/edit")
    async def edit_message(message_id: str, request: EditMessageRequest) -> JSONResponse:
        return ok(controller.edit_message(message_id, request))

    @app.patch("/api/studio/v1/runtime")
    async def update_runtime(request: RuntimeUpdateRequest) -> JSONResponse:
        return ok(controller.update_runtime(request))

    @app.post("/api/studio/v1/agents/{agent_id}/stop")
    async def stop_agent(agent_id: str) -> JSONResponse:
        return ok(controller.stop_agent(agent_id))

    @app.post("/api/studio/v1/agents/{agent_id}/prompt")
    async def inject_agent_prompt(agent_id: str, request: AgentPromptInjectRequest) -> JSONResponse:
        return ok(controller.inject_agent_prompt(agent_id, request))

    @app.get("/api/studio/v1/stream")
    async def stream(
        request: Request,
        cursor: str | None = None,
        run_id: str | None = None,
        agent_id: str | None = None,
    ) -> StreamingResponse:
        return StreamingResponse(  # pragma: no cover - _stream_events covers the streaming behavior directly.
            _stream_events(controller, request, cursor=cursor, run_id=run_id, agent_id=agent_id),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

    @app.get("/api/studio/v1/runs")
    async def runs() -> JSONResponse:
        return ok(controller.runs())

    @app.post("/api/studio/v1/runs/{run_id}/join")
    async def join_run(run_id: str) -> JSONResponse:
        return ok(controller.join_run(run_id))

    @app.get("/api/studio/v1/queue")
    async def queue() -> JSONResponse:
        return ok(controller.queue())

    @app.delete("/api/studio/v1/queue/{queue_item_id}")
    async def cancel_queue_item(queue_item_id: str) -> JSONResponse:
        return ok(controller.cancel_queue_item(queue_item_id))

    @app.post("/api/studio/v1/queue/clear")
    async def clear_queue(request: QueueClearRequest) -> JSONResponse:
        return ok(controller.clear_queue(request))

    @app.get("/api/studio/v1/checkpoints")
    async def checkpoints() -> JSONResponse:
        return ok(controller.checkpoints())

    @app.get("/api/studio/v1/checkpoints/{checkpoint_id}")
    async def checkpoint(checkpoint_id: str) -> JSONResponse:
        return ok(controller.checkpoint(checkpoint_id))

    @app.post("/api/studio/v1/checkpoints/{checkpoint_id}/resume")
    async def resume_checkpoint(checkpoint_id: str, request: CheckpointResumeRequest) -> JSONResponse:
        return ok(controller.resume_checkpoint(checkpoint_id, request))

    @app.get("/api/studio/v1/branches")
    async def branches() -> JSONResponse:
        return ok(controller.branches())

    @app.post("/api/studio/v1/branches")
    async def create_branch(request: BranchCreateRequest) -> JSONResponse:
        return ok(controller.create_branch(request))

    @app.post("/api/studio/v1/branches/{branch_id}/switch")
    async def switch_branch(branch_id: str) -> JSONResponse:
        return ok(controller.switch_branch(branch_id))

    @app.post("/api/studio/v1/branches/{branch_id}/archive")
    async def archive_branch(branch_id: str) -> JSONResponse:
        return ok(controller.archive_branch(branch_id))

    @app.patch("/api/studio/v1/ui-state")
    async def update_ui_state(request: StudioBranchUiStateUpdateRequest) -> JSONResponse:
        return ok(controller.update_ui_state(request))

    @app.get("/api/studio/v1/interrupts")
    async def interrupts() -> JSONResponse:
        return ok(controller.interrupts())

    @app.post("/api/studio/v1/interrupts/{interrupt_id}/resume")
    async def resume_interrupt(interrupt_id: str, request: InterruptResumeRequest) -> JSONResponse:
        return ok(controller.resume_interrupt(interrupt_id, request))

    @app.get("/api/studio/v1/files")
    async def files() -> JSONResponse:
        return ok(controller.files())

    @app.get("/api/studio/v1/workspace-files")
    async def workspace_files(query: str = "", limit: int = 20) -> JSONResponse:
        return ok(controller.workspace_files(query=query, limit=limit))

    @app.get("/api/studio/v1/files/{file_id}/preview")
    async def file_preview(file_id: str) -> FileResponse:
        resource = controller.file_resource(file_id, preview=True)
        return FileResponse(resource.path, media_type=resource.media_type)

    @app.get("/api/studio/v1/files/{file_id}/download")
    async def file_download_named(file_id: str) -> FileResponse:
        resource = controller.file_resource(file_id, allow_blocked=True)
        return FileResponse(resource.path, filename=resource.filename, media_type=resource.media_type)

    @app.get("/api/studio/v1/files/{file_id}")
    async def file_download(file_id: str) -> FileResponse:
        resource = controller.file_resource(file_id)
        return FileResponse(resource.path, filename=resource.filename, media_type=resource.media_type)

    @app.get("/api/studio/v1/changes")
    async def changes() -> JSONResponse:
        return ok(controller.changes())

    @app.get("/api/studio/v1/changes/{change_id}/diff")
    async def change_diff(change_id: str) -> JSONResponse:
        return ok(controller.change_diff(change_id))

    @app.post("/api/studio/v1/terminal/sessions")
    async def create_terminal_session() -> JSONResponse:
        return ok(controller.create_terminal_session())

    @app.get("/api/studio/v1/terminal/sessions/{session_id}/output")
    async def terminal_output(session_id: str, cursor: int = 0) -> JSONResponse:
        return ok(controller.terminal_output(session_id, cursor))

    @app.post("/api/studio/v1/terminal/sessions/{session_id}/input")
    async def terminal_input(session_id: str, body: dict[str, Any]) -> JSONResponse:
        return ok(controller.terminal_input(session_id, str(body.get("data") or "")))

    @app.post("/api/studio/v1/terminal/sessions/{session_id}/resize")
    async def terminal_resize(session_id: str, body: dict[str, Any]) -> JSONResponse:
        return ok(
            controller.terminal_resize(
                session_id,
                columns=int(body.get("columns") or 100),
                rows=int(body.get("rows") or 30),
            )
        )

    @app.delete("/api/studio/v1/terminal/sessions/{session_id}")
    async def terminate_terminal_session(session_id: str) -> JSONResponse:
        return ok(controller.terminate_terminal_session(session_id))

    @app.get("/api/state")
    async def compat_state() -> Any:
        return jsonable_encoder(controller.compat_state())

    @app.get("/api/activity")
    async def compat_activity(request: Request) -> Any:
        return jsonable_encoder(controller.compat_activity(request.url.query))

    @app.post("/api/messages")
    async def compat_append_message(body: dict[str, Any]) -> Any:
        return jsonable_encoder(controller.compat_append_message(body))

    @app.post("/api/runtime")
    async def compat_update_runtime(body: dict[str, Any]) -> Any:
        return jsonable_encoder(controller.compat_update_runtime(body))

    @app.post("/api/stop")
    async def compat_stop_agent(body: dict[str, Any]) -> Any:
        return jsonable_encoder(controller.compat_stop_agent(body))

    return app


async def _stream_events(
    controller: StudioApiController,
    request: Request,
    *,
    cursor: str | None,
    run_id: str | None,
    agent_id: str | None,
) -> AsyncIterator[str]:
    client_queue = StreamClientQueue()
    producer = asyncio.create_task(_produce_stream_events(controller, request, cursor=cursor, run_id=run_id, agent_id=agent_id, client_queue=client_queue))
    try:
        while True:
            frame = await client_queue.get()
            if frame is None:
                break
            yield frame
    finally:
        client_queue.close()
        producer.cancel()
        with suppress(asyncio.CancelledError):
            await producer


async def _produce_stream_events(
    controller: StudioApiController,
    request: Request,
    *,
    cursor: str | None,
    run_id: str | None,
    agent_id: str | None,
    client_queue: StreamClientQueue,
) -> None:
    effective_cursor = cursor or request.headers.get("last-event-id")
    hello = controller.stream_buffer.publish(
        "studio.hello",
        {
            "capabilities": StudioEnvelope.ok({}, capabilities=controller.capabilities()).capabilities.model_dump(mode="json"),
            "cursor": controller.stream_buffer.latest_cursor(),
            "run_id": run_id,
            "agent_id": agent_id,
        },
    )
    try:
        if not await client_queue.put(hello.to_sse()):
            return
        last_snapshot = controller.state().model_dump(mode="json")
        if effective_cursor is None:
            if not await client_queue.put(controller.stream_buffer.publish("snapshot.replace", last_snapshot).to_sse()):
                return
        else:
            replay = controller.stream_buffer.replay_after(effective_cursor)
            if replay is None:
                if not await client_queue.put(controller.stream_buffer.publish("snapshot.replace", last_snapshot).to_sse()):
                    return
            else:
                for frame in replay:
                    if frame.id != hello.id and frame.event not in {"studio.hello", "studio.heartbeat"}:
                        if not await client_queue.put(frame.to_sse()):
                            return
        while not await request.is_disconnected():
            await asyncio.sleep(15)
            snapshot = controller.state().model_dump(mode="json")
            if snapshot != last_snapshot:
                for event_name, payload in _snapshot_diff_events(last_snapshot, snapshot):
                    if not await client_queue.put(controller.stream_buffer.publish(event_name, payload).to_sse()):
                        return
                last_snapshot = snapshot
                if not await client_queue.put(controller.stream_buffer.publish("snapshot.replace", snapshot).to_sse()):
                    return
            if not await client_queue.put(controller.stream_buffer.publish("studio.heartbeat", {}).to_sse()):
                return
    finally:
        client_queue.close()


def _snapshot_diff_events(previous: dict[str, Any], current: dict[str, Any]) -> list[tuple[str, Any]]:
    events: list[tuple[str, Any]] = []
    events.extend(("activity.private_message.appended", payload) for payload in _new_private_messages(previous, current))
    events.extend(("checkpoint.observed", checkpoint) for checkpoint in _new_items_by_id(previous, current, "history", "checkpoints"))
    events.extend(
        ("generated_ui.validated", spec)
        for spec in _new_items_by_id(previous, current, "generated_ui")
        if spec.get("status") == "valid"
    )
    return events


def _new_private_messages(previous: dict[str, Any], current: dict[str, Any]) -> list[dict[str, Any]]:
    previous_threads = _private_threads_by_id(previous)
    messages = []
    for thread_id, thread in _private_threads_by_id(current).items():
        previous_count = len(previous_threads.get(thread_id, {}).get("messages", []))
        for message in thread.get("messages", [])[previous_count:]:
            messages.append(
                {
                    "agent_id": thread.get("agent_id"),
                    "thread_id": thread_id,
                    "message": message,
                }
            )
    return messages


def _private_threads_by_id(snapshot: dict[str, Any]) -> dict[str, dict[str, Any]]:
    activity = snapshot.get("activity", {})
    threads = activity.get("private_threads", []) if isinstance(activity, dict) else []
    return {str(thread.get("thread_id")): thread for thread in threads if isinstance(thread, dict) and thread.get("thread_id")}


def _new_items_by_id(snapshot: dict[str, Any], current: dict[str, Any], *path: str) -> list[dict[str, Any]]:
    previous_ids = {item["id"] for item in _items_at_path(snapshot, *path) if "id" in item}
    return [item for item in _items_at_path(current, *path) if item.get("id") not in previous_ids]


def _items_at_path(snapshot: dict[str, Any], *path: str) -> list[dict[str, Any]]:
    value: Any = snapshot
    for key in path:
        value = value.get(key, {}) if isinstance(value, dict) else {}
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, dict)]


def _ok(data: Any, *, capabilities: StudioCapabilities | None = None) -> JSONResponse:
    encoded = jsonable_encoder(data)
    return JSONResponse(StudioEnvelope.ok(encoded, capabilities=capabilities).model_dump(mode="json"))


def _error_response(status_code: int, error: StudioError, *, capabilities: StudioCapabilities | None = None) -> JSONResponse:
    return JSONResponse(StudioEnvelope.failed(error, capabilities=capabilities).model_dump(mode="json"), status_code=status_code)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Serve the Webapp Studio FastAPI backend.")
    parser.add_argument("team_file", nargs="?", help="Path to team.yaml.")
    parser.add_argument("--thread-id", help="Conversation id. Defaults to the team id.")
    parser.add_argument("--host", default="127.0.0.1", help="Host to bind.")
    parser.add_argument("--port", type=int, default=8765, help="Port to bind.")
    parser.add_argument("--var", action="append", default=[], help="Template variable in key=value form. Repeatable.")
    parser.add_argument("--config", action="append", default=[], help="Runtime configuration in key=value form. Repeatable.")
    parser.add_argument("--openai-api-key", help="OpenAI API key passed as runtime configuration.")
    parser.add_argument("--tavily-api-key", help="Tavily API key passed as runtime configuration.")
    parser.add_argument("--env-file", help="Path to a .env file. Defaults to .env in the current working directory.")
    parser.add_argument("--no-env-file", action="store_true", help="Do not load a .env file from the current working directory.")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    from src.webapp_studio.backend.application.studio_backend_launcher import StudioBackendLauncher

    args = parse_args(argv)
    StudioBackendLauncher().launch(
        team_file=args.team_file,
        variables=parse_key_value_pairs(args.var),
        config_variables=build_config_variables(args),
        conversation_id=args.thread_id,
        host=args.host,
        port=args.port,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
