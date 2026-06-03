from __future__ import annotations

import base64
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from src.team_instanciator.conversation.team import MentionAwareTeam
from src.team_loader.errors.team_loader_error import TeamLoaderError
from src.team_loader.loading.team_loader import TeamLoader
from src.team_loader.models._coercion import int_value, optional_int
from src.team_loader.models.team_definition import TeamDefinition
from src.type_defs import is_json_value
from src.webapp.attachments.attachment_ref_factory import AttachmentRefFactory
from src.webapp_studio.backend.api.studio_attachment_ref_factory import (
    MAX_ATTACHMENT_BYTES,
    MAX_ATTACHMENT_REQUEST_BYTES,
    StudioAttachmentRefFactory,
)


class EdgeCaseTests(unittest.TestCase):
    def test_small_validation_and_coercion_edges(self) -> None:
        self.assertFalse(is_json_value(object()))
        self.assertEqual(int_value("-3", 0), -3)
        self.assertEqual(optional_int("-2"), -2)
        self.assertIsNone(optional_int("nope"))
        self.assertEqual(MentionAwareTeam._optional_int(None, 5), 5)
        self.assertEqual(MentionAwareTeam._optional_int(None, "7"), 7)
        self.assertEqual(AttachmentRefFactory(SimpleNamespace()).refs("not-a-sequence", author_id="human"), [])

    def test_attachment_ref_factory_validates_base64_and_size_limits(self) -> None:
        created: list[dict[str, object]] = []

        def create_public_file_ref(*, filename, content, added_by, media_type=None):
            created.append(
                {
                    "filename": filename,
                    "content": content,
                    "added_by": added_by,
                    "media_type": media_type,
                }
            )
            return SimpleNamespace(id=f"file-{len(created)}", filename=filename)

        factory = StudioAttachmentRefFactory(SimpleNamespace(create_public_file_ref=create_public_file_ref))
        ref = factory.refs(
            [
                {
                    "filename": "notes.txt",
                    "content_base64": base64.b64encode(b"hello").decode("ascii"),
                    "media_type": "text/plain",
                },
                object(),
                {"id": "existing", "filename": "existing.txt"},
            ],
            author_id="human",
        )
        direct = factory.ref(
            {
                "filename": "direct.txt",
                "content_base64": base64.b64encode(b"direct").decode("ascii"),
            },
            author_id="human",
        )

        self.assertEqual(ref[0].filename, "notes.txt")
        self.assertEqual(ref[1]["id"], "existing")
        self.assertEqual(direct.filename, "direct.txt")
        self.assertEqual(created[0]["content"], b"hello")
        with self.assertRaisesRegex(ValueError, "base64"):
            factory.refs([{"filename": "bad.txt", "content_base64": "not base64!"}], author_id="human")
        with self.assertRaisesRegex(ValueError, "10 MiB"):
            factory.refs(
                [
                    {
                        "filename": "large.bin",
                        "content_base64": base64.b64encode(b"x" * (MAX_ATTACHMENT_BYTES + 1)).decode("ascii"),
                    }
                ],
                author_id="human",
            )
        with self.assertRaisesRegex(ValueError, "25 MiB"):
            factory.refs(
                [
                    {
                        "filename": f"part-{index}.bin",
                        "content_base64": base64.b64encode(
                            b"x" * (MAX_ATTACHMENT_REQUEST_BYTES // 3 + 1)
                        ).decode("ascii"),
                    }
                    for index in range(3)
                ],
                author_id="human",
            )

    def test_duplicate_case_insensitive_agent_ids_are_removed_from_lookup(self) -> None:
        self.assertEqual(TeamDefinition._case_insensitive_lookup(["Agent", "agent"]), {})

    def test_team_loader_rejects_template_output_that_is_not_a_mapping(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            team_file = Path(directory) / "team.yaml"
            team_file.write_text("id: team\nagents: {}\n", encoding="utf-8")
            renderer = SimpleNamespace(render_config_value=lambda _raw, _variables: [])

            with self.assertRaisesRegex(TeamLoaderError, "must render to a YAML mapping"):
                TeamLoader(template_renderer=renderer).load(team_file)


if __name__ == "__main__":
    unittest.main()
