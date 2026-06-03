from __future__ import annotations

import unittest
from pathlib import Path

from src.webapp_studio.backend.contracts.activity_snapshot import ActivitySnapshot
from src.webapp_studio.backend.contracts.agent_delivery_state_dto import AgentDeliveryStateDto
from src.webapp_studio.backend.contracts.append_message_request import AppendMessageRequest
from src.webapp_studio.backend.contracts.append_message_result import AppendMessageResult
from src.webapp_studio.backend.contracts.branch_create_request import BranchCreateRequest
from src.webapp_studio.backend.contracts.branch_summary import BranchSummary
from src.webapp_studio.backend.contracts.checkpoint_resume_request import CheckpointResumeRequest
from src.webapp_studio.backend.contracts.checkpoint_summary import CheckpointSummary
from src.webapp_studio.backend.contracts.conversation_delivery_dto import ConversationDeliveryDto
from src.webapp_studio.backend.contracts.conversation_event_dto import ConversationEventDto
from src.webapp_studio.backend.contracts.conversation_file_ref_dto import ConversationFileRefDto
from src.webapp_studio.backend.contracts.conversation_snapshot import ConversationSnapshot
from src.webapp_studio.backend.contracts.generated_ui_spec import GeneratedUiSpec
from src.webapp_studio.backend.contracts.health_status import HealthStatus
from src.webapp_studio.backend.contracts.history_snapshot import HistorySnapshot
from src.webapp_studio.backend.contracts.interrupt_request import InterruptRequest
from src.webapp_studio.backend.contracts.interrupt_resume_request import InterruptResumeRequest
from src.webapp_studio.backend.contracts.message_summary_dto import MessageSummaryDto
from src.webapp_studio.backend.contracts.queue_clear_request import QueueClearRequest
from src.webapp_studio.backend.contracts.queue_item import QueueItem
from src.webapp_studio.backend.contracts.run_join_result import RunJoinResult
from src.webapp_studio.backend.contracts.run_summary import RunSummary
from src.webapp_studio.backend.contracts.runtime_settings import RuntimeSettings
from src.webapp_studio.backend.contracts.runtime_update_request import RuntimeUpdateRequest
from src.webapp_studio.backend.contracts.stream_frame import StreamFrame
from src.webapp_studio.backend.contracts.studio_envelope import StudioEnvelope
from src.webapp_studio.backend.contracts.studio_error import StudioError
from src.webapp_studio.backend.contracts.studio_state import StudioState

FIXTURES = Path(__file__).parents[2] / "src" / "webapp_studio" / "contracts" / "fixtures"


class ContractFixtureTests(unittest.TestCase):
    def test_shared_json_fixtures_validate_through_pydantic(self) -> None:
        cases = {
            "activity_snapshot.json": ActivitySnapshot,
            "agent_delivery_state.json": AgentDeliveryStateDto,
            "append_message_request.json": AppendMessageRequest,
            "append_message_result.json": AppendMessageResult,
            "branch_create_request.json": BranchCreateRequest,
            "branch_summary.json": BranchSummary,
            "checkpoint_resume_edit_request.json": CheckpointResumeRequest,
            "checkpoint_resume_regenerate_request.json": CheckpointResumeRequest,
            "checkpoint_resume_request.json": CheckpointResumeRequest,
            "checkpoint_summary.json": CheckpointSummary,
            "conversation_delivery.json": ConversationDeliveryDto,
            "conversation_event.json": ConversationEventDto,
            "conversation_file_ref.json": ConversationFileRefDto,
            "conversation_snapshot.json": ConversationSnapshot,
            "generated_ui_spec.json": GeneratedUiSpec,
            "health_status.json": HealthStatus,
            "history_snapshot.json": HistorySnapshot,
            "interrupt_request.json": InterruptRequest,
            "interrupt_resume_request.json": InterruptResumeRequest,
            "message_summary.json": MessageSummaryDto,
            "queue_clear_request.json": QueueClearRequest,
            "queue_item.json": QueueItem,
            "run_join_result.json": RunJoinResult,
            "run_summary.json": RunSummary,
            "runtime_settings.json": RuntimeSettings,
            "runtime_update_request.json": RuntimeUpdateRequest,
            "stream_frame.json": StreamFrame,
            "studio_envelope.json": StudioEnvelope,
            "studio_error.json": StudioError,
            "studio_state.json": StudioState,
        }

        for filename, model in cases.items():
            with self.subTest(filename=filename):
                fixture = FIXTURES / filename
                parsed = model.model_validate_json(fixture.read_text())
                self.assertTrue(parsed.model_dump(mode="json"))

    def test_stream_frame_serializes_to_sse_wire_format(self) -> None:
        frame = StreamFrame.model_validate_json((FIXTURES / "stream_frame.json").read_text())

        self.assertIn("id: stream_00000001", frame.to_sse())
        self.assertIn("event: studio.hello", frame.to_sse())
        self.assertIn('"schema_version":"studio.v1"', frame.to_sse())


if __name__ == "__main__":
    unittest.main()
