from __future__ import annotations

import sqlite3

from src.team_instanciator.conversation.store import ConversationStore


class BranchThreadResolver:
    def __init__(self, connection: sqlite3.Connection | None, team_id: str) -> None:
        self._connection = connection
        self._team_id = team_id

    def resolve(
        self,
        *,
        parent_physical_thread_id: str,
        branch_id: str,
        logical_thread_key: str,
        target_physical_thread_id: str,
        created_by_commit_id: str | None = None,
    ) -> str:
        if self._connection is None or not branch_id:
            return target_physical_thread_id

        conversation_id = self._conversation_id(parent_physical_thread_id)
        branch_thread = ConversationStore(
            team_id=self._team_id,
            conversation_id=conversation_id,
            connection=self._connection,
        ).ensure_branch_thread(
            branch_id=branch_id,
            logical_thread_key=logical_thread_key,
            physical_thread_id=target_physical_thread_id,
            created_by_commit_id=created_by_commit_id,
        )
        return branch_thread.physical_thread_id

    def _conversation_id(self, thread_id: str) -> str:
        if ":branch:" in thread_id:
            return thread_id.split(":branch:", maxsplit=1)[0]
        if ":mention:" in thread_id:
            return thread_id.split(":mention:", maxsplit=1)[0]
        if ":relation:" in thread_id:
            return thread_id.split(":relation:", maxsplit=1)[0]
        return thread_id
