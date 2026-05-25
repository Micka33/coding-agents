from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from coding_agents.artifacts import ensure_agent_workflow_files
from coding_agents.readiness import (
    ReadinessGateError,
    assert_readiness_approved,
    read_readiness_gate,
    readiness_gate_path,
)


APPROVED_GATE = """approved: true
approval_scope: full_implementation
approved_by: Engineering Manager
approved_date: 2026-05-24
notes: Approved for testing.
"""


class ReadinessGateTests(unittest.TestCase):
    def test_artifact_initializer_creates_unapproved_yaml_without_overwrite(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            created = ensure_agent_workflow_files(root)
            gate_path = root / "docs/agent-workflow/readiness-gate.yaml"

            self.assertIn(gate_path, created)
            status = read_readiness_gate(root)
            self.assertFalse(status.approved)
            self.assertEqual(status.approval_scope, "none")
            with self.assertRaises(ReadinessGateError):
                assert_readiness_approved(root)

            gate_path.write_text(APPROVED_GATE, encoding="utf-8")
            created_again = ensure_agent_workflow_files(root)
            self.assertNotIn(gate_path, created_again)
            self.assertEqual(gate_path.read_text(encoding="utf-8"), APPROVED_GATE)

    def test_invalid_artifacts_dir_rejected_before_artifact_creation(self) -> None:
        invalid_dirs = ("", ".", "/", "/tmp/artifacts", "../docs", "docs/../workflow", "docs/*")

        for artifacts_dir in invalid_dirs:
            with self.subTest(artifacts_dir=artifacts_dir):
                with tempfile.TemporaryDirectory() as tmp:
                    root = Path(tmp)
                    with self.assertRaises(ValueError):
                        ensure_agent_workflow_files(root, artifacts_dir)
                    self.assertFalse((root / "docs").exists())

    def test_safe_custom_artifacts_dir_remains_repo_relative(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            created = ensure_agent_workflow_files(root, "project/governance/")

            self.assertIn(root / "project/governance/readiness-gate.yaml", created)
            self.assertEqual(
                readiness_gate_path(root, "project/governance"),
                root / "project/governance/readiness-gate.yaml",
            )

    def test_artifact_initializer_rejects_symlinked_artifacts_component(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "repo"
            outside = Path(tmp) / "outside"
            root.mkdir()
            outside.mkdir()
            try:
                (root / "docs").symlink_to(outside, target_is_directory=True)
            except OSError as exc:  # pragma: no cover - platform dependent
                self.skipTest(f"symlinks unavailable: {exc}")

            with self.assertRaisesRegex(ValueError, "symlink"):
                ensure_agent_workflow_files(root)
            self.assertFalse((outside / "agent-workflow").exists())

    def test_artifact_initializer_rejects_symlinked_existing_artifact_files(self) -> None:
        cases = (
            ("readiness-gate.md", "docs/agent-workflow/readiness-gate.yaml"),
            ("product-brief.md", "coding_agents/team.py"),
        )
        for artifact_name, target_name in cases:
            with self.subTest(artifact_name=artifact_name):
                with tempfile.TemporaryDirectory() as tmp:
                    root = Path(tmp)
                    artifact_dir = root / "docs/agent-workflow"
                    artifact_dir.mkdir(parents=True)
                    target = root / target_name
                    target.parent.mkdir(parents=True, exist_ok=True)
                    target.write_text("protected\n", encoding="utf-8")
                    try:
                        (artifact_dir / artifact_name).symlink_to(target)
                    except OSError as exc:  # pragma: no cover - platform dependent
                        self.skipTest(f"symlinks unavailable: {exc}")

                    with self.assertRaisesRegex(ValueError, "symlink"):
                        ensure_agent_workflow_files(root)

    def test_readiness_gate_rejects_symlinked_gate_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "repo"
            outside = Path(tmp) / "outside"
            gate_dir = root / "docs/agent-workflow"
            gate_dir.mkdir(parents=True)
            outside.mkdir()
            outside_gate = outside / "readiness-gate.yaml"
            outside_gate.write_text(APPROVED_GATE, encoding="utf-8")
            try:
                (gate_dir / "readiness-gate.yaml").symlink_to(outside_gate)
            except OSError as exc:  # pragma: no cover - platform dependent
                self.skipTest(f"symlinks unavailable: {exc}")

            with self.assertRaisesRegex(ReadinessGateError, "symlink"):
                read_readiness_gate(root)

    def test_readiness_gate_rejects_symlinked_artifacts_component(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "repo"
            outside = Path(tmp) / "outside"
            root.mkdir()
            gate_dir = outside / "agent-workflow"
            gate_dir.mkdir(parents=True)
            (gate_dir / "readiness-gate.yaml").write_text(APPROVED_GATE, encoding="utf-8")
            try:
                (root / "docs").symlink_to(outside, target_is_directory=True)
            except OSError as exc:  # pragma: no cover - platform dependent
                self.skipTest(f"symlinks unavailable: {exc}")

            with self.assertRaisesRegex(ReadinessGateError, "symlink"):
                read_readiness_gate(root)

    def test_missing_gate_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaisesRegex(ReadinessGateError, "missing"):
                read_readiness_gate(Path(tmp))

    def test_case_variant_readiness_gate_filename_does_not_approve_implementation(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            gate_dir = root / "docs/agent-workflow"
            gate_dir.mkdir(parents=True)
            (gate_dir / "READINESS-GATE.YAML").write_text(APPROVED_GATE, encoding="utf-8")

            with self.assertRaisesRegex(ReadinessGateError, "missing"):
                assert_readiness_approved(root)

    def test_invalid_gate_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            gate_dir = root / "docs/agent-workflow"
            gate_dir.mkdir(parents=True)
            (gate_dir / "readiness-gate.yaml").write_text(
                "approved: true\nnot a scalar line\n",
                encoding="utf-8",
            )

            with self.assertRaisesRegex(ReadinessGateError, "Invalid readiness gate"):
                read_readiness_gate(root)

    def test_unapproved_gate_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            gate_dir = root / "docs/agent-workflow"
            gate_dir.mkdir(parents=True)
            (gate_dir / "readiness-gate.yaml").write_text(
                """approved: false
approval_scope: full_implementation
approved_by: Human
approved_date: 2026-05-24
notes: Not approved.
""",
                encoding="utf-8",
            )

            with self.assertRaisesRegex(ReadinessGateError, "approved must be true"):
                assert_readiness_approved(root)

    def test_wrong_scope_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            gate_dir = root / "docs/agent-workflow"
            gate_dir.mkdir(parents=True)
            (gate_dir / "readiness-gate.yaml").write_text(
                APPROVED_GATE.replace("full_implementation", "limited_governance"),
                encoding="utf-8",
            )

            with self.assertRaisesRegex(ReadinessGateError, "approval_scope"):
                assert_readiness_approved(root)

    def test_missing_approval_metadata_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            gate_dir = root / "docs/agent-workflow"
            gate_dir.mkdir(parents=True)
            (gate_dir / "readiness-gate.yaml").write_text(
                """approved: true
approval_scope: full_implementation
approved_by: ""
approved_date: ""
notes: Missing metadata.
""",
                encoding="utf-8",
            )

            with self.assertRaisesRegex(ReadinessGateError, "approved_by"):
                assert_readiness_approved(root)

    def test_approved_full_implementation_gate_passes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            gate_dir = root / "docs/agent-workflow"
            gate_dir.mkdir(parents=True)
            (gate_dir / "readiness-gate.yaml").write_text(APPROVED_GATE, encoding="utf-8")

            status = assert_readiness_approved(root)

            self.assertTrue(status.approved)
            self.assertEqual(status.approval_scope, "full_implementation")
            self.assertEqual(status.approved_by, "Engineering Manager")


if __name__ == "__main__":
    unittest.main()
