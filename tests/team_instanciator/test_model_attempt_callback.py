from __future__ import annotations

import unittest
from uuid import UUID

from src.team_instanciator.conversation.store import ConversationStore
from src.team_instanciator.runtime.model_attempt_callback import ModelAttemptCallbackHandler


class ModelAttemptCallbackHandlerTests(unittest.TestCase):
    def test_records_attempt_lifecycle_and_retrying_failure(self) -> None:
        store = ConversationStore(team_id="team", conversation_id="thread")
        callback = ModelAttemptCallbackHandler(store=store, agent_id="agent", run_id="run_01", branch_id="branch_main")
        first_run_id = UUID("00000000-0000-0000-0000-000000000001")
        second_run_id = UUID("00000000-0000-0000-0000-000000000002")
        metadata = {
            "model_provider": "openai",
            "model_name": "openai:gpt-test",
            "model_reliability_max_attempts": 2,
            "model_reliability_timeout_mode": "stream_idle_timeout",
            "model_reliability_timeout_s": 120,
        }

        callback.on_chat_model_start({}, [], run_id=first_run_id, metadata=metadata)
        callback.on_llm_error(TimeoutError("idle"), run_id=first_run_id)
        callback.on_chat_model_start({}, [], run_id=second_run_id, metadata=metadata)
        callback.on_llm_end(object(), run_id=second_run_id)

        attempts = store.list_model_attempts(run_id="run_01")
        self.assertEqual([attempt.status for attempt in attempts], ["retrying", "success"])
        self.assertEqual(attempts[0].normalized_failure_code, "stream_idle_timeout")
        self.assertEqual(attempts[0].attempt_number, 1)
        self.assertEqual(attempts[1].attempt_number, 2)
        self.assertEqual(attempts[1].provider, "openai")


if __name__ == "__main__":
    unittest.main()
