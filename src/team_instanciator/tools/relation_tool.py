from __future__ import annotations

import threading
import uuid
from collections.abc import Mapping, Sequence

from langchain.tools import ToolRuntime

from src.team_loader.models.relation_definition import RelationDefinition

from src.team_instanciator.conversation.protocols import GraphRegistry
from src.team_instanciator.runtime.branch_thread_resolver import BranchThreadResolver
from src.team_instanciator.runtime.runnable_config_metadata_injector import RunnableConfigMetadataInjector
from src.team_instanciator.runtime.thread_id_factory import ThreadIdFactory
from src.team_instanciator.runtime.tool_call_edge import ToolCallEdge
from src.team_instanciator.runtime.tool_call_edge_recorder import ToolCallEdgeRecorder


_LOGICAL_THREAD_LOCKS: dict[tuple[str, str], threading.Lock] = {}
_LOGICAL_THREAD_LOCKS_GUARD = threading.Lock()


class RelationTool:
    def __init__(
        self,
        relation: RelationDefinition,
        registry: GraphRegistry,
        parent_thread_id: str,
        thread_id_factory: ThreadIdFactory,
        checkpoint_metadata: Mapping[str, object],
        tool_call_edge_recorder: ToolCallEdgeRecorder | None = None,
        branch_thread_resolver: BranchThreadResolver | None = None,
        metadata_injector: RunnableConfigMetadataInjector | None = None,
    ) -> None:
        self._relation = relation
        self._registry = registry
        self._fallback_parent_thread_id = parent_thread_id
        self._thread_id_factory = thread_id_factory
        self._checkpoint_metadata = dict(checkpoint_metadata)
        self._tool_call_edge_recorder = tool_call_edge_recorder or ToolCallEdgeRecorder()
        self._branch_thread_resolver = branch_thread_resolver
        self._metadata_injector = metadata_injector or RunnableConfigMetadataInjector()

    def run(self, message: str, runtime: ToolRuntime) -> str:
        """Send a message to a related agent."""

        graph = self._registry.graph(self._relation.target)
        parent_thread_id = self._parent_thread_id(runtime)
        thread_id = self._thread_id_factory.relation(parent_thread_id, self._relation)
        runtime_metadata = self._runtime_metadata(runtime)
        branch_id = self._thread_id_factory.branch_id_from_thread_id(parent_thread_id) or self._metadata_value(runtime_metadata, "branch_id") or ""
        parent_logical_thread_key = self._thread_id_factory.logical_thread_key(parent_thread_id)
        child_logical_thread_key = self._thread_id_factory.logical_thread_key(thread_id)
        edge_id = self._tool_call_id(runtime) or f"edge_{uuid.uuid4().hex}"
        commit_id = f"commit_{edge_id}"
        thread_id = self._physical_thread_id(
            parent_physical_thread_id=parent_thread_id,
            branch_id=branch_id,
            logical_thread_key=child_logical_thread_key,
            target_physical_thread_id=thread_id,
            created_by_commit_id=commit_id,
        )
        metadata = {
            **self._checkpoint_metadata,
            "branch_id": branch_id,
            "parent_logical_thread_key": parent_logical_thread_key,
            "parent_physical_thread_id": parent_thread_id,
            "relation_id": self._thread_id_factory.relation_id(self._relation),
            "logical_thread_key": child_logical_thread_key,
            "physical_thread_id": thread_id,
            "run_id": self._metadata_value(runtime_metadata, "run_id") or "",
            "tool_call_edge_id": edge_id,
            "commit_id": commit_id,
        }
        edge = ToolCallEdge(
            id=edge_id,
            commit_id=commit_id,
            branch_id=branch_id,
            parent_logical_thread_key=parent_logical_thread_key,
            parent_physical_thread_id=parent_thread_id,
            relation_id=self._thread_id_factory.relation_id(self._relation),
            target_agent_id=self._relation.target,
            child_logical_thread_key=child_logical_thread_key,
            child_physical_thread_id=thread_id,
            run_id=metadata["run_id"] or None,
            status="running",
        )
        lock = self._logical_thread_lock(branch_id, child_logical_thread_key)
        with lock:
            self._tool_call_edge_recorder.record_started(edge)
            try:
                result = graph.invoke(
                    {"messages": [{"role": "user", "content": message}]},
                    config=self._metadata_injector.inject(
                        {"configurable": {"thread_id": thread_id}},
                        metadata,
                    ),
                )
            except Exception:
                self._tool_call_edge_recorder.record_finished(edge_id, "failed")
                raise
            self._tool_call_edge_recorder.record_finished(edge_id, "success")
        return self._last_message_text(result)

    def _parent_thread_id(self, runtime: ToolRuntime) -> str:
        configurable = runtime.config.get("configurable", {}) if runtime.config else {}
        thread_id = configurable.get("thread_id")
        if isinstance(thread_id, str) and thread_id:
            return thread_id
        return self._fallback_parent_thread_id

    def _runtime_metadata(self, runtime: ToolRuntime) -> Mapping[str, object]:
        metadata = runtime.config.get("metadata", {}) if runtime.config else {}
        return metadata if isinstance(metadata, Mapping) else {}

    def _metadata_value(self, metadata: Mapping[str, object], key: str) -> str | None:
        value = metadata.get(key)
        return value if isinstance(value, str) and value else None

    def _tool_call_id(self, runtime: ToolRuntime) -> str | None:
        value = getattr(runtime, "tool_call_id", None)
        return value if isinstance(value, str) and value else None

    def _logical_thread_lock(self, branch_id: str, logical_thread_key: str) -> threading.Lock:
        key = (branch_id, logical_thread_key)
        with _LOGICAL_THREAD_LOCKS_GUARD:
            lock = _LOGICAL_THREAD_LOCKS.get(key)
            if lock is None:
                lock = threading.Lock()
                _LOGICAL_THREAD_LOCKS[key] = lock
            return lock

    def _physical_thread_id(
        self,
        *,
        parent_physical_thread_id: str,
        branch_id: str,
        logical_thread_key: str,
        target_physical_thread_id: str,
        created_by_commit_id: str,
    ) -> str:
        if self._branch_thread_resolver is None:
            return target_physical_thread_id
        return self._branch_thread_resolver.resolve(
            parent_physical_thread_id=parent_physical_thread_id,
            branch_id=branch_id,
            logical_thread_key=logical_thread_key,
            target_physical_thread_id=target_physical_thread_id,
            created_by_commit_id=created_by_commit_id,
        )

    def _last_message_text(self, result: object) -> str:
        messages = result.get("messages") if isinstance(result, Mapping) else None
        if not isinstance(messages, Sequence) or isinstance(messages, (str, bytes, bytearray)) or not messages:
            return str(result)
        last = messages[-1]
        content = getattr(last, "content", None)
        if content is None and isinstance(last, Mapping):
            content = last.get("content")
        return "" if content is None else str(content)
