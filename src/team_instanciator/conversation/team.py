from __future__ import annotations

import mimetypes
import shutil
import uuid
from collections.abc import Iterable, Mapping
from pathlib import Path
from typing import TypeAlias

from langchain_core.messages import HumanMessage
from langgraph.checkpoint.serde.jsonplus import JsonPlusSerializer
from langgraph.graph.message import add_messages
from langgraph.types import Overwrite

from src.type_defs import JsonObject, is_json_value
from src.team_loader.models.team_definition import TeamDefinition
from src.team_instanciator.factories.checkpoint_metadata_factory import CheckpointMetadataFactory
from src.team_instanciator.runtime.checkpointer_handle import CheckpointerHandle
from src.team_instanciator.runtime.thread_id_factory import ThreadIdFactory

from .conversation_append_result import ConversationAppendResult
from .conversation_checkpoint_resume_result import ConversationCheckpointResumeResult
from .conversation_event import ConversationEvent
from .conversation_file_ref import ConversationFileRef
from .payloads import ConversationStateDict, MessageSummaryDict
from .conversation_runtime_controller import ConversationRuntimeController
from .mention_parser import MentionParser
from .protocols import GraphRegistry
from .reply_extractor import PublicReplyExtractor
from .router import MentionRouter
from .store import ConversationStore
from .sync_builder import AgentSyncBuilder

ConversationFileInput: TypeAlias = str | Path | ConversationFileRef | JsonObject


class MentionAwareTeam:
    def __init__(
        self,
        *,
        team: TeamDefinition,
        registry: GraphRegistry,
        checkpointer_handle: CheckpointerHandle,
        root_dir: Path,
        conversation_id: str,
        thread_id_factory: ThreadIdFactory,
        checkpoint_metadata_factory: CheckpointMetadataFactory,
    ) -> None:
        if team.conversation is None:
            raise ValueError("MentionAwareTeam requires a top-level conversation configuration.")
        self.team = team
        self.registry = registry
        self.checkpointer_handle = checkpointer_handle
        self.root_dir = root_dir
        self.conversation_id = conversation_id
        self.thread_id_factory = thread_id_factory
        self.checkpoint_metadata_factory = checkpoint_metadata_factory
        self.store = ConversationStore(
            team_id=team.id,
            conversation_id=conversation_id,
            connection=checkpointer_handle.connection,
            default_max_cascade_turns=team.conversation.mentions.max_cascade_turns,
        )
        self.parser = MentionParser.from_team(team)
        participants = tuple(
            team.agents[agent_id]
            for agent_id, reference in team.agent_references.items()
            if reference.conversation is not None
        )
        self.aliases_by_participant = {
            agent_id: reference.conversation.aliases
            for agent_id, reference in team.agent_references.items()
            if reference.conversation is not None
        }
        self.router = MentionRouter(
            team=team,
            registry=registry,
            store=self.store,
            parser=self.parser,
            sync_builder=AgentSyncBuilder(
                identity_refresh_after_tokens=team.conversation.identity_refresh_after_tokens,
                participants=participants,
                aliases_by_participant=self.aliases_by_participant,
            ),
            reply_extractor=PublicReplyExtractor(),
            thread_id_factory=thread_id_factory,
            checkpoint_metadata_factory=checkpoint_metadata_factory,
            root_thread_id=conversation_id,
        )
        self.runtime = ConversationRuntimeController(self)
        self._serde = JsonPlusSerializer()
        for participant in self.parser.participants:
            self.store.ensure_agent_state(participant)

    def with_conversation_id(self, conversation_id: str) -> MentionAwareTeam:
        if conversation_id == self.conversation_id:
            return self
        return MentionAwareTeam(
            team=self.team,
            registry=self.registry,
            checkpointer_handle=self.checkpointer_handle,
            root_dir=self.root_dir,
            conversation_id=conversation_id,
            thread_id_factory=self.thread_id_factory,
            checkpoint_metadata_factory=self.checkpoint_metadata_factory,
        )

    def append_human_message(
        self,
        content: str,
        *,
        author_id: str = "human",
        files: Iterable[ConversationFileInput] | None = None,
        metadata: Mapping[str, object] | None = None,
        wait: bool = True,
    ) -> ConversationAppendResult:
        attachments = tuple(self._file_ref(file, added_by=author_id) for file in files or ())
        mentions = self.parser.parse(content, author_id=author_id)
        event = self.store.append_event(
            author_id=author_id,
            author_kind="human",
            content=content,
            mentions=mentions,
            attachments=attachments,
            metadata=metadata,
        )
        deliveries_before = len(self.store.list_deliveries())
        runtime_state = self.store.get_runtime_state()
        if runtime_state.mention_hook_enabled:
            targets = mentions
            if not targets and content.strip():
                targets = self.team.conversation.human_input.default_targets
            self.router.enqueue_targets(event, tuple(targets))
            self.router.dispatch(wait=wait)
        deliveries = tuple(self.store.list_deliveries()[deliveries_before:])
        return ConversationAppendResult(event=event, deliveries=deliveries)

    def edit_human_message(
        self,
        event_id: str,
        content: str,
        *,
        author_id: str = "human",
        wait: bool = True,
    ) -> ConversationAppendResult:
        current_branch_id = self.store.current_branch_id()
        visible_events = self.store.list_events(branch_id=current_branch_id)
        edited_index = next((index for index, event in enumerate(visible_events) if event.id == event_id), None)
        if edited_index is None:
            raise ValueError("message event is not visible in the current branch.")
        edited_event = visible_events[edited_index]
        if edited_event.author_kind != "human":
            raise ValueError("only human messages can be edited.")

        previous_event = visible_events[edited_index - 1] if edited_index > 0 else None
        branch = self.store.create_branch(
            label=f"Edit #{edited_event.seq}",
            origin_checkpoint_id=edited_event.frontier_before_event_id,
            origin_event_id=edited_event.id,
            origin_event_seq=previous_event.seq if previous_event is not None else 0,
            parent_branch_id=current_branch_id,
        )
        self.store.switch_branch(branch.id)
        mentions = self.parser.parse(content, author_id=author_id)
        event = self.store.append_event(
            author_id=author_id,
            author_kind="human",
            content=content,
            branch_id=branch.id,
            logical_message_id=edited_event.logical_message_id or edited_event.id,
            version_parent_event_id=edited_event.id,
            parent_event_id=previous_event.id if previous_event is not None else None,
            frontier_before_event_id=edited_event.frontier_before_event_id,
            mentions=mentions,
            attachments=edited_event.attachments,
            metadata={
                "edited_from_event_id": edited_event.id,
                "edited_from_branch_id": current_branch_id,
            },
        )
        deliveries_before = len(self.store.list_deliveries(branch_id=branch.id))
        runtime_state = self.store.get_runtime_state()
        if runtime_state.mention_hook_enabled:
            targets = mentions
            if not targets and content.strip():
                targets = self.team.conversation.human_input.default_targets
            self.router.enqueue_targets(event, tuple(targets))
            self.router.dispatch(wait=wait)
        deliveries = tuple(self.store.list_deliveries(branch_id=branch.id)[deliveries_before:])
        return ConversationAppendResult(event=event, deliveries=deliveries)

    def append_agent_message(
        self,
        *,
        agent_id: str,
        content: str,
        source_thread_id: str | None = None,
        source_message_id: str | None = None,
    ) -> ConversationEvent:
        mentions = self.parser.parse(content, author_id=agent_id)
        event = self.store.append_event(
            author_id=agent_id,
            author_kind="agent",
            content=content,
            mentions=mentions,
            source_thread_id=source_thread_id,
            source_message_id=source_message_id,
        )
        if mentions and self.store.get_runtime_state().mention_hook_enabled:
            self.router.enqueue_targets(event, mentions)
            self.router.dispatch(wait=False)
        return event

    def wait_for_idle(self) -> None:
        self.router.wait_for_idle()

    def resume_checkpoint(
        self,
        *,
        checkpoint_id: str,
        checkpoint_ns: str,
        thread_id: str,
        mode: str = "resume",
        edited_content: str | None = None,
        origin_event_id: str | None = None,
        origin_event_seq: int | None = None,
    ) -> ConversationCheckpointResumeResult:
        agent_id = self._agent_id_from_thread(thread_id)
        if agent_id is None:
            raise ValueError("checkpoint thread is not a mention thread.")
        graph = self.registry.graph(agent_id)
        config: dict[str, object] = {
            "configurable": {
                "thread_id": thread_id,
                "checkpoint_ns": checkpoint_ns,
                "checkpoint_id": checkpoint_id,
            }
        }
        if mode == "edit":
            if not edited_content:
                raise ValueError("edited_content is required for checkpoint edit.")
            update_state = getattr(graph, "update_state", None)
            if not callable(update_state):
                raise ValueError("checkpoint edit requires graph.update_state support.")
            config = update_state(
                config,
                {
                    "messages": [
                        HumanMessage(
                            name="human",
                            content=edited_content,
                            response_metadata={
                                "conversation_event_id": origin_event_id,
                                "conversation_seq": origin_event_seq,
                            },
                        )
                    ]
                },
            )
        result = graph.invoke(None, config=config)
        reply = PublicReplyExtractor().extract(result)
        if reply is None:
            raise ValueError("Checkpoint replay returned no final textual AI reply.")
        branch = self.store.create_branch(
            label=self._checkpoint_branch_label(mode),
            origin_checkpoint_id=checkpoint_id,
            origin_event_id=origin_event_id,
            origin_event_seq=origin_event_seq,
            head_checkpoint_id=checkpoint_id,
            parent_branch_id=self.store.current_branch_id(),
        )
        self.store.switch_branch(branch.id)
        logical_thread_key = self.thread_id_factory.logical_thread_key(thread_id)
        self.store.create_control_event(
            branch_id=branch.id,
            logical_thread_key=logical_thread_key,
            physical_thread_id=thread_id,
            parent_run_id=None,
            kind=f"checkpoint-{mode}",
            content=edited_content if mode == "edit" and edited_content is not None else "",
        )
        event = self.store.append_event(
            author_id=agent_id,
            author_kind="agent",
            content=reply.content,
            mentions=self.parser.parse(reply.content, author_id=agent_id),
            source_thread_id=thread_id,
            source_message_id=reply.source_message_id,
            metadata={
                "branch_id": branch.id,
                "checkpoint_id": checkpoint_id,
                "time_travel_mode": mode,
            },
        )
        return ConversationCheckpointResumeResult(branch=branch, event=event, mode=mode)

    def state(self) -> ConversationStateDict:
        events = [event.to_dict() for event in self.store.list_events()]
        agent_states = [state.to_dict() for state in self.store.list_agent_states()]
        deliveries = [delivery.to_dict() for delivery in self.store.list_deliveries()]
        branch_threads = [thread.to_dict() for thread in self.store.list_branch_threads()]
        thread_frontiers = [frontier.to_dict() for frontier in self.store.list_thread_frontiers()]
        control_events = [event.to_dict() for event in self.store.list_control_events()]
        activities = [state for state in agent_states if state["running"] or state["queued"]]
        return {
            "team_id": self.team.id,
            "conversation_id": self.conversation_id,
            "participants": sorted(self.parser.participants),
            "participant_aliases": {
                participant: list(self.aliases_by_participant.get(participant, ()))
                for participant in sorted(self.parser.participants)
            },
            "runtime": self.store.get_runtime_state().to_dict(),
            "events": events,
            "agent_states": agent_states,
            "deliveries": deliveries,
            "branch_threads": branch_threads,
            "thread_frontiers": thread_frontiers,
            "control_events": control_events,
            "activities": activities,
            "activity": activities[0] if activities else None,
        }

    def activity(self, agent_id: str | None = None) -> ConversationStateDict:
        state = self.state()
        if agent_id:
            state["agent_states"] = [item for item in state["agent_states"] if item["agent_id"] == agent_id]
            state["deliveries"] = [item for item in state["deliveries"] if item["agent_id"] == agent_id]
        if agent_id:
            private_thread_id = self.thread_id_factory.mention(
                self.thread_id_factory.branch(self.conversation_id, self.store.current_branch_id()),
                agent_id,
            )
            state["private_thread_id"] = private_thread_id
            state["private_messages"] = self._private_messages(private_thread_id)
            state["control_events"] = [
                item for item in state["control_events"] if item["physical_thread_id"] == private_thread_id
            ]
        return state

    def create_public_file_ref(
        self,
        *,
        filename: str,
        content: bytes,
        added_by: str,
        media_type: str | None = None,
    ) -> ConversationFileRef:
        file_id = f"file_{uuid.uuid4().hex}"
        destination_dir = self.root_dir / ".coding-agents" / "conversations" / self.conversation_id / "files"
        destination_dir.mkdir(parents=True, exist_ok=True)
        destination = destination_dir / file_id
        destination.write_bytes(content)
        return ConversationFileRef(
            id=file_id,
            filename=filename,
            uri=f"conversation://files/{file_id}",
            media_type=media_type or mimetypes.guess_type(filename)[0],
            size_bytes=destination.stat().st_size,
            added_by=added_by,
        )

    def _private_messages(self, thread_id: str) -> list[MessageSummaryDict]:
        connection = self.checkpointer_handle.connection
        if connection is None:
            return []
        try:
            rows = self._private_message_rows(connection, thread_id)
        except Exception:
            return []

        messages: list[object] = []
        created_at_by_key: dict[str, str] = {}
        for type_name, value, checkpoint_type, checkpoint_value in rows:
            try:
                loaded = self._serde.loads_typed((type_name, value))
            except Exception:
                continue
            checkpoint_created_at = self._checkpoint_created_at(checkpoint_type, checkpoint_value)
            if isinstance(loaded, Overwrite):
                messages = list(loaded.value if isinstance(loaded.value, list) else [loaded.value])
                self._remember_message_timestamps(created_at_by_key, messages, checkpoint_created_at)
            else:
                previous_keys = {self._message_timestamp_key(message) for message in messages}
                loaded_messages = list(loaded if isinstance(loaded, list) else [loaded])
                messages = add_messages(messages, loaded)
                new_keys = {self._message_timestamp_key(message) for message in messages} - previous_keys
                new_messages = [
                    message
                    for message in messages
                    if self._message_timestamp_key(message) in new_keys
                ]
                self._remember_message_timestamps(
                    created_at_by_key,
                    loaded_messages + new_messages,
                    checkpoint_created_at,
                )
        return [
            self._message_summary(message, created_at=self._message_created_at(created_at_by_key, message))
            for message in messages
        ]

    def _private_message_rows(self, connection, thread_id: str) -> list[tuple[object, object, object, object]]:
        try:
            return list(
                connection.execute(
                    """
                    select w.type, w.value, c.type, c.checkpoint
                    from writes w
                    left join checkpoints c
                      on c.thread_id = w.thread_id
                     and c.checkpoint_ns = w.checkpoint_ns
                     and c.checkpoint_id = w.checkpoint_id
                    where w.thread_id = ? and w.checkpoint_ns = '' and w.channel = 'messages'
                    order by w.checkpoint_id asc, w.task_id asc, w.idx asc
                    """,
                    (thread_id,),
                ).fetchall()
            )
        except Exception:
            return [
                (type_name, value, None, None)
                for type_name, value in connection.execute(
                    """
                    select type, value
                    from writes
                    where thread_id = ? and checkpoint_ns = '' and channel = 'messages'
                    order by checkpoint_id asc, task_id asc, idx asc
                    """,
                    (thread_id,),
                ).fetchall()
            ]

    def _checkpoint_created_at(self, type_name: object, value: object) -> str | None:
        if not type_name or value is None:
            return None
        try:
            loaded = self._serde.loads_typed((str(type_name), value))
        except Exception:
            return None
        if not isinstance(loaded, Mapping):
            return None
        timestamp = loaded.get("ts") or loaded.get("created_at")
        return str(timestamp).replace("+00:00", "Z") if timestamp else None

    def _remember_message_timestamps(
        self,
        created_at_by_key: dict[str, str],
        messages: list[object],
        created_at: str | None,
    ) -> None:
        if created_at is None:
            return
        for message in messages:
            created_at_by_key[self._message_timestamp_key(message)] = created_at

    def _message_created_at(self, created_at_by_key: Mapping[str, str], message: object) -> str | None:
        return created_at_by_key.get(self._message_timestamp_key(message))

    def _message_timestamp_key(self, message: object) -> str:
        raw_id = message.get("id") if isinstance(message, Mapping) else getattr(message, "id", None)
        if raw_id:
            return f"id:{raw_id}"
        return f"object:{id(message)}"

    def _checkpoint_branch_label(self, mode: str) -> str:
        if mode == "edit":
            return "Checkpoint edit"
        if mode == "regenerate":
            return "Checkpoint regenerate"
        return "Checkpoint resume"

    def _agent_id_from_thread(self, thread_id: str) -> str | None:
        marker = ":mention:"
        if marker not in thread_id:
            return None
        agent_id = thread_id.rsplit(marker, maxsplit=1)[-1]
        return agent_id if agent_id in self.parser.participants else None

    def _message_summary(
        self,
        message: object,
        *,
        created_at: str | None = None,
    ) -> MessageSummaryDict:
        content = getattr(message, "content", "")
        if isinstance(message, Mapping):
            content = message.get("content", "")
        tool_calls = (
            getattr(message, "tool_calls", None)
            if not isinstance(message, Mapping)
            else message.get("tool_calls")
        )
        summary: MessageSummaryDict = {
            "type": str(
                getattr(message, "type", None)
                or (message.get("role") if isinstance(message, Mapping) else None)
                or "message"
            ),
            "name": self._optional_text(
                getattr(message, "name", None)
                if not isinstance(message, Mapping)
                else message.get("name")
            ),
            "content": self._content_text(content),
            "tool_calls": tool_calls if tool_calls is not None and is_json_value(tool_calls) else [],
        }
        if created_at is not None:
            summary["created_at"] = created_at
        return summary

    def _content_text(self, content: object) -> str:
        if isinstance(content, str):
            return content
        if isinstance(content, list):
            parts: list[str] = []
            for item in content:
                if isinstance(item, Mapping):
                    text = item.get("text") or item.get("content") or item.get("reasoning")
                    if text:
                        parts.append(str(text))
                elif item:
                    parts.append(str(item))
            return "\n".join(parts)
        return "" if content is None else str(content)

    def _file_ref(self, file: ConversationFileInput, *, added_by: str) -> ConversationFileRef:
        if isinstance(file, ConversationFileRef):
            return file
        if isinstance(file, Mapping):
            return ConversationFileRef(
                id=str(file.get("id") or f"file_{uuid.uuid4().hex}"),
                filename=str(file.get("filename") or file.get("name") or "attachment"),
                uri=str(file.get("uri") or ""),
                media_type=self._optional_text(file.get("media_type")),
                size_bytes=self._optional_int(file.get("size_bytes")),
                added_by=str(file.get("added_by") or added_by),
            )

        source = Path(file).expanduser().resolve()
        file_id = f"file_{uuid.uuid4().hex}"
        destination_dir = self.root_dir / ".coding-agents" / "conversations" / self.conversation_id / "files"
        destination_dir.mkdir(parents=True, exist_ok=True)
        destination = destination_dir / file_id
        shutil.copy2(source, destination)
        return ConversationFileRef(
            id=file_id,
            filename=source.name,
            uri=f"conversation://files/{file_id}",
            media_type=mimetypes.guess_type(source.name)[0],
            size_bytes=destination.stat().st_size,
            added_by=added_by,
        )

    def _optional_text(self, value: object) -> str | None:
        return str(value) if value is not None else None

    def _optional_int(self, value: object) -> int | None:
        if isinstance(value, int):
            return value
        if isinstance(value, str) and value.isdigit():
            return int(value)
        return None
