from __future__ import annotations

import unittest
from uuid import UUID

from src.team_instanciator.conversation.store import ConversationStore
from src.team_instanciator.runtime.model_attempt_callback import ModelAttemptCallbackHandler, with_model_attempt_callback


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

    def test_handles_unknown_runs_metadata_defaults_and_callback_shapes(self) -> None:
        store = ConversationStore(team_id="team", conversation_id="thread")
        callback = ModelAttemptCallbackHandler(store=store, agent_id="agent", run_id="run_01", branch_id="branch_main")
        unknown_run_id = UUID("00000000-0000-0000-0000-000000000099")
        failed_run_id = UUID("00000000-0000-0000-0000-000000000003")
        parsed_run_id = UUID("00000000-0000-0000-0000-000000000004")
        defaulted_run_id = UUID("00000000-0000-0000-0000-000000000005")

        self.assertIsNone(callback.on_llm_end(object(), run_id=unknown_run_id))
        self.assertIsNone(callback.on_llm_error(RuntimeError("missing"), run_id=unknown_run_id))

        callback.on_chat_model_start(
            {},
            [],
            run_id=failed_run_id,
            metadata={
                "model_provider": "",
                "model_name": object(),
                "model_reliability_max_attempts": "bad",
                "model_reliability_timeout_s": "bad",
            },
        )
        callback.on_llm_error(RuntimeError("fatal"), run_id=failed_run_id)
        callback.on_chat_model_start(
            {},
            [],
            run_id=parsed_run_id,
            metadata={
                "model_reliability_max_attempts": "3",
                "model_reliability_timeout_s": "2.5",
            },
        )
        callback.on_llm_end(object(), run_id=parsed_run_id)
        callback.on_chat_model_start(
            {},
            [],
            run_id=defaulted_run_id,
            metadata={
                "model_reliability_max_attempts": object(),
                "model_reliability_timeout_s": object(),
            },
        )
        callback.on_llm_end(object(), run_id=defaulted_run_id)

        attempts = store.list_model_attempts(run_id="run_01")
        self.assertEqual(attempts[0].status, "failed")
        self.assertEqual(attempts[0].provider, "unknown")
        self.assertEqual(attempts[0].model, "unknown")
        self.assertEqual(attempts[0].max_attempts, 1)
        self.assertEqual(attempts[0].timeout_seconds, 0.0)
        self.assertEqual(attempts[1].max_attempts, 3)
        self.assertEqual(attempts[1].timeout_seconds, 2.5)
        self.assertEqual(attempts[2].max_attempts, 1)
        self.assertEqual(attempts[2].timeout_seconds, 0.0)

        none_config = with_model_attempt_callback(
            {},
            store=store,
            agent_id="agent",
            run_id="run_none",
            branch_id="branch_main",
        )
        list_config = with_model_attempt_callback(
            {"callbacks": ["existing"]},
            store=store,
            agent_id="agent",
            run_id="run_02",
            branch_id="branch_main",
        )
        tuple_config = with_model_attempt_callback(
            {"callbacks": ("existing",)},
            store=store,
            agent_id="agent",
            run_id="run_03",
            branch_id="branch_main",
        )
        object_config = with_model_attempt_callback(
            {"callbacks": "existing"},
            store=store,
            agent_id="agent",
            run_id="run_04",
            branch_id="branch_main",
        )

        self.assertIsInstance(none_config["callbacks"][0], ModelAttemptCallbackHandler)
        self.assertEqual(list_config["callbacks"][0], "existing")
        self.assertEqual(tuple_config["callbacks"][0], "existing")
        self.assertEqual(object_config["callbacks"][0], "existing")
        self.assertIsInstance(list_config["callbacks"][1], ModelAttemptCallbackHandler)
        self.assertIsInstance(tuple_config["callbacks"][1], ModelAttemptCallbackHandler)
        self.assertIsInstance(object_config["callbacks"][1], ModelAttemptCallbackHandler)


if __name__ == "__main__":
    unittest.main()
