from __future__ import annotations

import threading
import uuid

from src.team_loader.models.team_definition import TeamDefinition
from src.team_instanciator.factories.checkpoint_metadata_factory import CheckpointMetadataFactory
from src.team_instanciator.runtime.graph_invocation import invoke_graph_sync
from src.team_instanciator.runtime.model_attempt_callback import with_model_attempt_callback
from src.team_instanciator.runtime.runnable_config_metadata_injector import RunnableConfigMetadataInjector
from src.team_instanciator.runtime.thread_id_factory import ThreadIdFactory

from .conversation_event import ConversationEvent
from .dispatch_context import DispatchContext
from .mention_parser import MentionParser
from .protocols import GraphRegistry
from .reply_extractor import PublicReplyExtractor
from .store import ConversationStore
from .sync_builder import AgentSyncBuilder


class MentionRouter:
    def __init__(
        self,
        *,
        team: TeamDefinition,
        registry: GraphRegistry,
        store: ConversationStore,
        parser: MentionParser,
        sync_builder: AgentSyncBuilder,
        reply_extractor: PublicReplyExtractor,
        thread_id_factory: ThreadIdFactory,
        checkpoint_metadata_factory: CheckpointMetadataFactory,
        root_thread_id: str,
        metadata_injector: RunnableConfigMetadataInjector | None = None,
    ) -> None:
        self._team = team
        self._registry = registry
        self._store = store
        self._parser = parser
        self._sync_builder = sync_builder
        self._reply_extractor = reply_extractor
        self._thread_id_factory = thread_id_factory
        self._checkpoint_metadata_factory = checkpoint_metadata_factory
        self._root_thread_id = root_thread_id
        self._metadata_injector = metadata_injector or RunnableConfigMetadataInjector()
        self._dispatch_lock = threading.Lock()
        self._background_lock = threading.Lock()
        self._background_thread: threading.Thread | None = None

    def enqueue_targets(self, event: ConversationEvent, targets: tuple[str, ...]) -> None:
        for target in targets:
            self._store.enqueue(target, event.seq, branch_id=event.branch_id)

    def dispatch(self, *, wait: bool = True) -> None:
        if wait:
            self.drain()
            return
        with self._background_lock:
            if self._background_thread is not None and self._background_thread.is_alive():
                return
            self._background_thread = threading.Thread(target=self.drain, name="mention-router", daemon=True)
            self._background_thread.start()

    def drain(self) -> None:
        if not self._dispatch_lock.acquire(blocking=False):
            return
        context = DispatchContext()
        try:
            while True:
                branch_id = self._store.current_branch_id()
                available = max(0, self._team.conversation.mentions.max_parallel_agents - self._store.running_count(branch_id=branch_id))
                if available <= 0:
                    return
                agent_ids = self._store.pending_idle_agent_ids(limit=available, branch_id=branch_id)
                if not agent_ids:
                    return
                threads = [
                    threading.Thread(
                        target=self._run_agent,
                        args=(agent_id, context),
                        name=f"mention-router:{agent_id}",
                    )
                    for agent_id in agent_ids
                ]
                for thread in threads:
                    thread.start()
                for thread in threads:
                    thread.join()
        finally:
            self._dispatch_lock.release()

    def stop(self, agent_id: str) -> None:
        state = self._store.request_stop(agent_id)
        graph = self._registry.graph(agent_id) if state.running else None
        interrupt = getattr(graph, "interrupt", None)
        if callable(interrupt):
            try:
                interrupt()
            except Exception:
                pass

    def append_public_reply(
        self,
        agent_id: str,
        content: str,
        *,
        source_thread_id: str,
        source_message_id: str | None,
        run_id: str | None = None,
        branch_id: str,
        context: DispatchContext,
    ) -> ConversationEvent:
        return self._append_public_reply(
            agent_id,
            content,
            source_thread_id=source_thread_id,
            source_message_id=source_message_id,
            run_id=run_id,
            branch_id=branch_id,
            context=context,
        )

    def wait_for_idle(self) -> None:
        thread = self._background_thread
        if thread is not None and thread.is_alive():
            thread.join()

    def _run_agent(self, agent_id: str, context: DispatchContext) -> None:
        branch_id = self._store.current_branch_id()
        state = self._store.ensure_agent_state(agent_id, branch_id=branch_id)
        events = self._store.list_events(after_seq=state.last_delivered_seq, branch_id=branch_id)
        if not events:
            self._store.complete_run(
                agent_id,
                run_id=state.current_run_id or "",
                snapshot_seq=state.last_delivered_seq,
                delivered=False,
                identity_inserted=False,
                token_estimate=0,
                branch_id=branch_id,
            )
            return

        snapshot_seq = max(event.seq for event in events)
        run_id = f"run_{uuid.uuid4().hex}"
        target = self._team.agents[agent_id]
        proposed_thread_id = self._thread_id_factory.mention(
            self._thread_id_factory.branch(self._root_thread_id, branch_id),
            agent_id,
        )
        logical_thread_key = self._thread_id_factory.logical_thread_key(proposed_thread_id)
        branch_thread = self._store.ensure_branch_thread(
            branch_id=branch_id,
            logical_thread_key=logical_thread_key,
            physical_thread_id=proposed_thread_id,
            created_by_commit_id=run_id,
        )
        thread_id = branch_thread.physical_thread_id
        self._store.mark_run_started(
            agent_id,
            run_id=run_id,
            snapshot_seq=snapshot_seq,
            branch_id=branch_id,
            logical_thread_key=logical_thread_key,
            physical_thread_id=thread_id,
        )

        try:
            sync = self._sync_builder.build(target=target, state=state, events=events)
            if sync.projected_event_count == 0:
                self._store.complete_run(
                    agent_id,
                    run_id=run_id,
                    snapshot_seq=snapshot_seq,
                    delivered=True,
                    identity_inserted=False,
                    token_estimate=sync.token_estimate,
                    branch_id=branch_id,
                )
                self._store.record_delivery(
                    agent_id=agent_id,
                    run_id=run_id,
                    snapshot_seq=snapshot_seq,
                    status="skipped",
                    branch_id=branch_id,
                )
                return

            graph = self._registry.graph(agent_id)
            config = self._metadata_injector.inject(
                {"configurable": {"thread_id": thread_id}},
                {
                    **self._checkpoint_metadata_factory.mention(self._team, target),
                    "branch_id": branch_id,
                    "logical_thread_key": logical_thread_key,
                    "physical_thread_id": thread_id,
                    "run_id": run_id,
                },
            )
            result = invoke_graph_sync(
                graph,
                {"messages": sync.messages},
                config=with_model_attempt_callback(
                    config,
                    store=self._store,
                    agent_id=agent_id,
                    run_id=run_id,
                    branch_id=branch_id,
                ),
            )
            if self._store.is_stop_requested(agent_id, run_id, branch_id=branch_id):
                self._store.complete_run(
                    agent_id,
                    run_id=run_id,
                    snapshot_seq=snapshot_seq,
                    delivered=False,
                    identity_inserted=False,
                    token_estimate=0,
                    branch_id=branch_id,
                )
                self._store.record_delivery(
                    agent_id=agent_id,
                    run_id=run_id,
                    snapshot_seq=snapshot_seq,
                    status="stopped",
                    branch_id=branch_id,
                )
                return

            delivered = self._store.complete_run(
                agent_id,
                run_id=run_id,
                snapshot_seq=snapshot_seq,
                delivered=True,
                identity_inserted=sync.identity_inserted,
                token_estimate=sync.token_estimate,
                branch_id=branch_id,
            )
            if not delivered:
                self._store.record_delivery(
                    agent_id=agent_id,
                    run_id=run_id,
                    snapshot_seq=snapshot_seq,
                    status="ignored",
                    branch_id=branch_id,
                )
                return

            reply = self._reply_extractor.extract(result)
            if reply is None:
                self._store.record_delivery(
                    agent_id=agent_id,
                    run_id=run_id,
                    snapshot_seq=snapshot_seq,
                    status="empty",
                    error="Agent run returned no final textual AI reply.",
                    branch_id=branch_id,
                )
                return

            self._store.record_delivery(agent_id=agent_id, run_id=run_id, snapshot_seq=snapshot_seq, status="success", branch_id=branch_id)
            self._append_public_reply(
                agent_id,
                reply.content,
                source_thread_id=thread_id,
                source_message_id=reply.source_message_id,
                run_id=run_id,
                branch_id=branch_id,
                context=context,
            )
        except Exception as exc:
            self._store.complete_run(
                agent_id,
                run_id=run_id,
                snapshot_seq=snapshot_seq,
                delivered=False,
                identity_inserted=False,
                token_estimate=0,
                branch_id=branch_id,
            )
            self._store.record_delivery(
                agent_id=agent_id,
                run_id=run_id,
                snapshot_seq=snapshot_seq,
                status="failed",
                error=str(exc),
                branch_id=branch_id,
            )

    def _append_public_reply(
        self,
        agent_id: str,
        content: str,
        *,
        source_thread_id: str,
        source_message_id: str | None,
        run_id: str | None = None,
        branch_id: str,
        context: DispatchContext,
    ) -> ConversationEvent:
        mentions = self._parser.parse(content, author_id=agent_id)
        event = self._store.append_event(
            author_id=agent_id,
            author_kind="agent",
            content=content,
            branch_id=branch_id,
            mentions=mentions,
            source_thread_id=source_thread_id,
            source_message_id=source_message_id,
        )
        logical_thread_key = self._thread_id_factory.logical_thread_key(source_thread_id)
        checkpoint_id = self._store.latest_checkpoint_id(source_thread_id)
        if checkpoint_id is not None and event.frontier_after_event_id is not None:
            self._store.record_thread_frontier(
                frontier_id=event.frontier_after_event_id,
                branch_id=branch_id,
                event_id=event.id,
                event_boundary="after",
                logical_thread_key=logical_thread_key,
                physical_thread_id=source_thread_id,
                checkpoint_id=checkpoint_id,
                run_id=run_id,
                usable_for_fork=True,
                usable_for_continue=True,
            )
        self._record_tool_call_frontiers(
            frontier_id=event.frontier_after_event_id,
            event_id=event.id,
            branch_id=branch_id,
            run_id=run_id,
        )
        if not mentions or not self._store.get_runtime_state().mention_hook_enabled:
            return event

        max_cascade_turns = self._store.get_runtime_state().max_cascade_turns
        if max_cascade_turns is not None and context.cascade_turns >= max_cascade_turns:
            self._store.record_delivery(
                agent_id=agent_id,
                status="cascade-limited",
                snapshot_seq=event.seq,
                error=f"max_cascade_turns={max_cascade_turns} reached.",
                branch_id=branch_id,
            )
            return event

        context.cascade_turns += 1
        self.enqueue_targets(event, mentions)
        return event

    def _record_tool_call_frontiers(
        self,
        *,
        frontier_id: str | None,
        event_id: str,
        branch_id: str,
        run_id: str | None,
    ) -> None:
        if frontier_id is None or run_id is None:
            return
        for edge in self._store.list_tool_call_edges(branch_id=branch_id, run_id=run_id, status="success"):
            checkpoint_id = self._store.latest_checkpoint_id(edge.child_physical_thread_id)
            if checkpoint_id is None:
                continue
            self._store.record_thread_frontier(
                frontier_id=frontier_id,
                branch_id=branch_id,
                event_id=event_id,
                event_boundary="after",
                logical_thread_key=edge.child_logical_thread_key,
                physical_thread_id=edge.child_physical_thread_id,
                checkpoint_id=checkpoint_id,
                run_id=run_id,
                parent_logical_thread_key=edge.parent_logical_thread_key,
                usable_for_fork=True,
                usable_for_continue=True,
            )
