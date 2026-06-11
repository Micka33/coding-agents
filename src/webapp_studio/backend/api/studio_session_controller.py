from __future__ import annotations

import uuid
import sqlite3
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any

from src.team_instanciator.configuration.runtime_configuration import RuntimeConfiguration
from src.team_instanciator.core.team_instanciator import TeamInstanciator
from src.team_instanciator.errors.team_instanciator_error import TeamInstanciatorError
from src.team_loader.parsing.yaml_parser import YamlParser
from src.type_defs import JsonObject
from src.type_defs import is_json_object
from src.webapp_studio.backend.api.studio_api_controller import StudioApiController
from src.webapp_studio.backend.api.studio_api_error import StudioApiError
from src.webapp_studio.backend.api.studio_workspace_file_browser import StudioWorkspaceFileBrowser
from src.webapp_studio.backend.api.team_discovery_service import TeamDiscoveryService, duplicate_team_id_message
from src.webapp_studio.backend.contracts.append_message_request import AppendMessageRequest
from src.webapp_studio.backend.contracts.conversation_create_request import ConversationCreateRequest
from src.webapp_studio.backend.contracts.health_status import HealthStatus
from src.webapp_studio.backend.contracts.studio_capabilities import StudioCapabilities
from src.webapp_studio.backend.streaming.stream_buffer import StreamBuffer
from src.webapp_studio.backend.api.time_utils import utc_now_iso


class StudioSessionController:
    def __init__(
        self,
        *,
        repository_root: Path,
        workspace_dir: Path,
        team_file: str | Path | None = None,
        variables: JsonObject | None = None,
        config_variables: Mapping[str, object] | None = None,
        conversation_id: str | None = None,
        stream_buffer: StreamBuffer | None = None,
        instanciator_factory: Callable[..., TeamInstanciator] = TeamInstanciator,
    ) -> None:
        self._repository_root = repository_root.resolve()
        self._workspace_dir = workspace_dir.resolve()
        self._team_file = Path(team_file).expanduser().resolve() if team_file is not None else None
        self._variables = variables
        self._config_variables = config_variables
        self._stream_buffer = stream_buffer or StreamBuffer()
        self._instanciator_factory = instanciator_factory
        self._started_at = utc_now_iso()
        self._discovery = TeamDiscoveryService(
            repository_root=self._repository_root,
            workspace_dir=self._workspace_dir,
        ).discover(explicit_team_file=self._team_file)
        self._configuration = RuntimeConfiguration(config_variables)
        self._yaml_parser = YamlParser()
        self._instances: dict[str, Any] = {}
        self._active: StudioApiController | None = None
        if self._team_file is not None and not self.discovery_blocked:
            try:
                self._activate_explicit_team(conversation_id)
            except Exception:
                self.close()
                raise

    @property
    def stream_buffer(self) -> StreamBuffer:
        return self._stream_buffer

    @property
    def discovery_blocked(self) -> bool:
        return self._discovery.get("status") == "blocked"

    def discovery_error_message(self) -> str | None:
        return duplicate_team_id_message(self._discovery)

    def close(self) -> None:
        for instantiated in self._instances.values():
            close = getattr(instantiated, "close", None)
            if callable(close):
                close()
        self._instances.clear()

    def capabilities(self) -> StudioCapabilities:
        if self._active is None:
            return StudioCapabilities()
        return self._active.capabilities()

    def health(self) -> HealthStatus:
        if self._active is not None:
            return self._active.health()
        return HealthStatus(started_at=self._started_at)

    def teams(self) -> dict[str, Any]:
        return self._discovery

    def state(self) -> Any:
        return self._require_active().state()

    def activity(self, agent_id: str | None = None) -> Any:
        return self._require_active().activity(agent_id)

    def append_message(self, request: AppendMessageRequest) -> Any:
        return self._require_active().append_message(request)

    def create_conversation(self, request: ConversationCreateRequest) -> dict[str, Any]:
        self._ensure_discovery_ready()
        if not request.initial_message.strip():
            raise StudioApiError(
                status_code=400,
                code="invalid_request",
                message="initial_message is required",
                field="initial_message",
            )
        conversation_id = self._generated_conversation_id(request.team_id)
        active = self._activate_team(request.team_id, conversation_id)
        result = active.append_message(
            AppendMessageRequest(
                content=request.initial_message,
                author_id=request.author_id,
                attachments=request.attachments,
                workspace_paths=request.workspace_paths,
                wait=request.wait,
                client_message_id=request.client_message_id,
            )
        )
        state = active.state()
        return {
            "session": active.session(),
            "state": state.model_dump(mode="json"),
            "append": result.model_dump(mode="json"),
        }

    def edit_message(self, message_id: str, request: Any) -> Any:
        return self._require_active().edit_message(message_id, request)

    def session(self) -> dict[str, Any]:
        if self._active is not None:
            return self._active.session()
        return {
            "team_id": None,
            "conversation_id": None,
            "team_file": None,
            "launcher_cwd": str(self._workspace_dir),
            "resolved_root_dir": str(self._workspace_dir),
            "checkpointer": None,
            "loaded_at": self._started_at,
        }

    def conversations(self, limit: int = 20) -> dict[str, Any]:
        current_session = self.session()
        persisted = self._persisted_conversations(limit)
        if persisted:
            return {
                "team_id": current_session["team_id"],
                "current_conversation_id": current_session["conversation_id"],
                "conversations": persisted,
            }
        if self._active is None:
            return {
                "team_id": None,
                "current_conversation_id": None,
                "conversations": [],
            }
        return self._active.conversations(limit)

    def switch_conversation(self, conversation_id: str, team_id: str | None = None) -> dict[str, Any]:
        if team_id:
            active = self._activate_team(team_id, conversation_id)
            state = active.state()
            payload = {
                "session": active.session(),
                "state": state.model_dump(mode="json"),
            }
            self._stream_buffer.publish("snapshot.replace", state.model_dump(mode="json"))
            return payload
        return self._require_active().switch_conversation(conversation_id)

    def files(self) -> Any:
        return self._require_active().files()

    def workspace_files(self, *, query: str = "", limit: int = 20) -> Any:
        if self._active is not None:
            return self._active.workspace_files(query=query, limit=limit)
        self._ensure_discovery_ready()
        return StudioWorkspaceFileBrowser(self._workspace_dir).files(query=query, limit=limit)

    def changes(self) -> Any:
        return self._require_active().changes()

    def change_diff(self, change_id: str) -> Any:
        return self._require_active().change_diff(change_id)

    def create_terminal_session(self) -> Any:
        return self._require_active().create_terminal_session()

    def terminal_output(self, session_id: str, cursor: int = 0) -> Any:
        return self._require_active().terminal_output(session_id, cursor)

    def terminal_input(self, session_id: str, data: str) -> Any:
        return self._require_active().terminal_input(session_id, data)

    def terminal_resize(self, session_id: str, *, columns: int, rows: int) -> Any:
        return self._require_active().terminal_resize(session_id, columns=columns, rows=rows)

    def terminate_terminal_session(self, session_id: str) -> Any:
        return self._require_active().terminate_terminal_session(session_id)

    def update_runtime(self, request: Any) -> Any:
        return self._require_active().update_runtime(request)

    def stop_agent(self, agent_id: str) -> Any:
        return self._require_active().stop_agent(agent_id)

    def inject_agent_prompt(self, agent_id: str, request: Any) -> Any:
        return self._require_active().inject_agent_prompt(agent_id, request)

    def runs(self) -> Any:
        return self._require_active().runs()

    def join_run(self, run_id: str) -> Any:
        return self._require_active().join_run(run_id)

    def queue(self) -> Any:
        return self._require_active().queue()

    def cancel_queue_item(self, queue_item_id: str) -> Any:
        return self._require_active().cancel_queue_item(queue_item_id)

    def clear_queue(self, request: Any) -> Any:
        return self._require_active().clear_queue(request)

    def checkpoints(self) -> Any:
        return self._require_active().checkpoints()

    def checkpoint(self, checkpoint_id: str) -> Any:
        return self._require_active().checkpoint(checkpoint_id)

    def resume_checkpoint(self, checkpoint_id: str, request: Any) -> Any:
        return self._require_active().resume_checkpoint(checkpoint_id, request)

    def branches(self) -> Any:
        return self._require_active().branches()

    def create_branch(self, request: Any) -> Any:
        return self._require_active().create_branch(request)

    def switch_branch(self, branch_id: str) -> Any:
        return self._require_active().switch_branch(branch_id)

    def archive_branch(self, branch_id: str) -> Any:
        return self._require_active().archive_branch(branch_id)

    def update_ui_state(self, request: Any) -> Any:
        return self._require_active().update_ui_state(request)

    def interrupts(self) -> Any:
        return self._require_active().interrupts()

    def resume_interrupt(self, interrupt_id: str, request: Any) -> Any:
        return self._require_active().resume_interrupt(interrupt_id, request)

    def file_resource(self, file_id: str, *, allow_blocked: bool = False, preview: bool = False) -> Any:
        return self._require_active().file_resource(file_id, allow_blocked=allow_blocked, preview=preview)

    def compat_state(self) -> Any:
        return self._require_active().compat_state()

    def compat_activity(self, query: str) -> Any:
        return self._require_active().compat_activity(query)

    def compat_append_message(self, body: JsonObject) -> Any:
        return self._require_active().compat_append_message(body)

    def compat_update_runtime(self, body: JsonObject) -> Any:
        return self._require_active().compat_update_runtime(body)

    def compat_stop_agent(self, body: dict[str, object]) -> Any:
        return self._require_active().compat_stop_agent(body)

    def _activate_explicit_team(self, conversation_id: str | None) -> None:
        self._ensure_explicit_team_not_colliding()
        descriptor = self._team_for_file(self._team_file) or {
            "team_id": str(self._team_file),
            "team_file": str(self._team_file),
        }
        instantiated = self._instance_for(descriptor)
        conversation = instantiated.conversation_for(conversation_id)
        if conversation is None:
            raise ValueError("Selected team has no top-level conversation section.")
        self._dispatch_pending(conversation)
        self._active = StudioApiController(conversation, stream_buffer=self._stream_buffer)

    def _activate_team(self, team_id: str, conversation_id: str) -> StudioApiController:
        self._ensure_discovery_ready()
        if not conversation_id.strip():
            raise StudioApiError(
                status_code=400,
                code="invalid_request",
                message="conversation_id is required",
                field="conversation_id",
            )
        descriptor = self._team_for_id(team_id)
        if descriptor is None:
            raise StudioApiError(status_code=404, code="not_found", message="team not found", field="team_id")
        instantiated = self._instance_for(descriptor)
        conversation = instantiated.conversation_for(conversation_id.strip())
        if conversation is None:
            raise StudioApiError(
                status_code=400,
                code="invalid_request",
                message="Selected team has no top-level conversation section.",
                field="team_id",
            )
        self._dispatch_pending(conversation)
        self._active = StudioApiController(conversation, stream_buffer=self._stream_buffer)
        return self._active

    def _instance_for(self, descriptor: dict[str, Any]) -> Any:
        team_id = str(descriptor["team_id"])
        existing = self._instances.get(team_id)
        if existing is not None:
            return existing
        instanciator = self._instanciator_factory(config_variables=self._config_variables)
        try:
            instantiated = instanciator.instantiate(descriptor["team_file"], self._variables)
        except TeamInstanciatorError as error:
            raise StudioApiError(
                status_code=409,
                code="team_instantiation_failed",
                message=str(error),
                field="team_id",
            ) from error
        self._instances[team_id] = instantiated
        return instantiated

    def _team_for_id(self, team_id: str) -> dict[str, Any] | None:
        normalized = team_id.casefold()
        for team in self._discovery.get("teams", []):
            if str(team.get("team_id", "")).casefold() == normalized:
                return team
        return None

    def _team_for_file(self, team_file: Path | None) -> dict[str, Any] | None:
        if team_file is None:
            return None
        for team in self._discovery.get("teams", []):
            if Path(str(team.get("team_file"))).resolve() == team_file:
                return team
        return None

    def _ensure_discovery_ready(self) -> None:
        if self.discovery_blocked:
            raise StudioApiError(
                status_code=409,
                code="team_discovery_blocked",
                message="Team discovery is blocked by duplicate team ids.",
                details={"duplicate_ids": self._discovery.get("duplicate_ids", [])},
            )

    def _ensure_explicit_team_not_colliding(self) -> None:
        team_file = str(self._team_file)
        for duplicate in self._discovery.get("duplicate_ids", []):
            if team_file in duplicate.get("team_files", []):
                raise ValueError(
                    f"Team file {team_file} collides with duplicate team id \"{duplicate.get('team_id')}\". "
                    "Rename one of the colliding team.yaml ids."
                )

    def _dispatch_pending(self, conversation: Any) -> None:
        dispatch_pending = getattr(conversation, "dispatch_pending", None)
        if callable(dispatch_pending):
            dispatch_pending(wait=False)

    def _require_active(self) -> StudioApiController:
        self._ensure_discovery_ready()
        if self._active is None:
            raise StudioApiError(
                status_code=409,
                code="conversation_required",
                message="Start a new chat before using this Studio endpoint.",
            )
        return self._active

    def _generated_conversation_id(self, team_id: str) -> str:
        prefix = "".join(char.lower() if char.isalnum() else "-" for char in team_id).strip("-") or "conversation"
        return f"{prefix}-{uuid.uuid4().hex[:12]}"

    def _persisted_conversations(self, limit: int) -> list[dict[str, Any]]:
        if self.discovery_blocked:
            return []
        conversations = []
        for team in self._discovery.get("teams", []):
            sqlite_path = self._sqlite_path_for_team(team)
            if sqlite_path is None or not sqlite_path.is_file():
                continue
            conversations.extend(self._sqlite_conversations(team, sqlite_path, limit))
        conversations.sort(key=lambda item: str(item.get("last_event_at") or ""), reverse=True)
        return conversations[: max(1, min(limit, 100))]

    def _sqlite_conversations(self, team: dict[str, Any], sqlite_path: Path, limit: int) -> list[dict[str, Any]]:
        try:
            connection = sqlite3.connect(f"file:{sqlite_path}?mode=ro", uri=True)
        except sqlite3.Error:
            return []
        try:
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
                (str(team["team_id"]), max(1, min(limit, 100))),
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
                    (str(team["team_id"]), conversation_id, last_seq),
                ).fetchone()
                first_human = connection.execute(
                    """
                    select content
                    from team_conversation_events
                    where team_id = ? and conversation_id = ? and author_kind = 'human'
                    order by seq asc
                    limit 1
                    """,
                    (str(team["team_id"]), conversation_id),
                ).fetchone()
                title = self._summary_text(str(first_human[0])) if first_human is not None else str(conversation_id)
                conversations.append(
                    {
                        "team_id": str(team["team_id"]),
                        "conversation_id": str(conversation_id),
                        "title": title,
                        "preview": title,
                        "event_count": int(event_count),
                        "last_seq": int(last_seq or 0),
                        "last_event_at": str(last_event_at) if last_event_at is not None else None,
                        "last_author_id": str(last_author[0]) if last_author is not None else None,
                    }
                )
            return conversations
        except sqlite3.Error:
            return []
        finally:
            connection.close()

    def _sqlite_path_for_team(self, team: dict[str, Any]) -> Path | None:
        try:
            parsed = self._yaml_parser.parse(Path(str(team["team_file"])).read_text(encoding="utf-8"))
        except (OSError, KeyError):
            return None
        if not is_json_object(parsed):
            return None
        defaults = parsed.get("defaults")
        defaults_mapping = defaults if is_json_object(defaults) else {}
        checkpointer = defaults_mapping.get("checkpointer")
        checkpointer_mapping = checkpointer if is_json_object(checkpointer) else {}
        backend = self._configured_value(checkpointer_mapping.get("env"), checkpointer_mapping.get("default")) or "memory"
        if str(backend) != "sqlite":
            return None
        sqlite_path = checkpointer_mapping.get("sqlite_path")
        sqlite_mapping = sqlite_path if is_json_object(sqlite_path) else {}
        raw_sqlite_path = self._configured_value(sqlite_mapping.get("env"), sqlite_mapping.get("default")) or ".team-instanciator/checkpoints.sqlite"
        path = Path(str(raw_sqlite_path))
        if path.is_absolute():
            return path
        return (self._workspace_dir / path).resolve()

    def _configured_value(self, env_name: object, default: object) -> object:
        if env_name:
            configured = self._configuration.get(str(env_name))
            if configured:
                return configured
        return default

    def _summary_text(self, content: str) -> str:
        compact = " ".join(content.split())
        if not compact:
            return "Untitled conversation"
        if len(compact) <= 80:
            return compact
        return f"{compact[:77]}..."
