from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from uuid import UUID

from langchain_core.callbacks import BaseCallbackHandler

from src.team_instanciator.conversation.store import ConversationStore
from src.team_instanciator.resolvers.model_reliability import classify_model_exception


@dataclass(frozen=True)
class _AttemptContext:
    attempt_id: str
    attempt_number: int
    max_attempts: int


class ModelAttemptCallbackHandler(BaseCallbackHandler):
    def __init__(self, *, store: ConversationStore, agent_id: str, run_id: str, branch_id: str) -> None:
        self._store = store
        self._agent_id = agent_id
        self._run_id = run_id
        self._branch_id = branch_id
        self._attempt_count = 0
        self._attempts_by_model_run_id: dict[str, _AttemptContext] = {}

    def on_chat_model_start(
        self,
        serialized: dict[str, Any],
        messages: list[list[Any]],
        *,
        run_id: UUID,
        parent_run_id: UUID | None = None,
        tags: list[str] | None = None,
        metadata: dict[str, Any] | None = None,
        **kwargs: Any,
    ) -> Any:
        del serialized, messages, parent_run_id, tags, kwargs
        self._attempt_count += 1
        model_run_id = str(run_id)
        attempt_id = f"model_attempt_{run_id.hex}"
        max_attempts = self._int_metadata(metadata, "model_reliability_max_attempts", 1)
        context = _AttemptContext(
            attempt_id=attempt_id,
            attempt_number=self._attempt_count,
            max_attempts=max_attempts,
        )
        self._attempts_by_model_run_id[model_run_id] = context
        self._store.record_model_attempt_started(
            attempt_id=attempt_id,
            run_id=self._run_id,
            agent_id=self._agent_id,
            provider=self._str_metadata(metadata, "model_provider", "unknown"),
            model=self._str_metadata(metadata, "model_name", "unknown"),
            attempt_number=context.attempt_number,
            max_attempts=context.max_attempts,
            timeout_mode=self._str_metadata(metadata, "model_reliability_timeout_mode", "non_streaming_timeout"),
            timeout_seconds=self._float_metadata(metadata, "model_reliability_timeout_s", 0.0),
            branch_id=self._branch_id,
        )

    def on_llm_end(
        self,
        response: Any,
        *,
        run_id: UUID,
        parent_run_id: UUID | None = None,
        tags: list[str] | None = None,
        **kwargs: Any,
    ) -> Any:
        del response, parent_run_id, tags, kwargs
        context = self._attempts_by_model_run_id.get(str(run_id))
        if context is None:
            return None
        self._store.record_model_attempt_finished(context.attempt_id, status="success")
        return None

    def on_llm_error(
        self,
        error: BaseException,
        *,
        run_id: UUID,
        parent_run_id: UUID | None = None,
        tags: list[str] | None = None,
        **kwargs: Any,
    ) -> Any:
        del parent_run_id, tags, kwargs
        context = self._attempts_by_model_run_id.get(str(run_id))
        if context is None:
            return None
        classification = classify_model_exception(error)
        status = "retrying" if classification.retryable and context.attempt_number < context.max_attempts else "failed"
        self._store.record_model_attempt_finished(
            context.attempt_id,
            status=status,
            normalized_failure_code=classification.failure_code,
            provider_error_type=classification.provider_error_type,
        )
        return None

    def _str_metadata(self, metadata: dict[str, Any] | None, key: str, default: str) -> str:
        value = metadata.get(key) if metadata else None
        return value if isinstance(value, str) and value else default

    def _int_metadata(self, metadata: dict[str, Any] | None, key: str, default: int) -> int:
        value = metadata.get(key) if metadata else None
        if isinstance(value, int):
            return value
        if isinstance(value, str):
            try:
                return int(value)
            except ValueError:
                return default
        return default

    def _float_metadata(self, metadata: dict[str, Any] | None, key: str, default: float) -> float:
        value = metadata.get(key) if metadata else None
        if isinstance(value, (float, int)):
            return float(value)
        if isinstance(value, str):
            try:
                return float(value)
            except ValueError:
                return default
        return default


def with_model_attempt_callback(
    config: dict[str, Any],
    *,
    store: ConversationStore,
    agent_id: str,
    run_id: str,
    branch_id: str,
) -> dict[str, Any]:
    updated = dict(config)
    callback = ModelAttemptCallbackHandler(store=store, agent_id=agent_id, run_id=run_id, branch_id=branch_id)
    existing_callbacks = updated.get("callbacks")
    if existing_callbacks is None:
        updated["callbacks"] = [callback]
    elif isinstance(existing_callbacks, list):
        updated["callbacks"] = [*existing_callbacks, callback]
    elif isinstance(existing_callbacks, tuple):
        updated["callbacks"] = [*existing_callbacks, callback]
    else:
        updated["callbacks"] = [existing_callbacks, callback]
    return updated
