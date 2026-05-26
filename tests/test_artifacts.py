from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from coding_agents.artifacts import ARTIFACT_TEMPLATES, ensure_agent_workflow_files


class ArtifactTemplateTests(unittest.TestCase):
    def test_initializer_creates_complete_workflow_template_set(self) -> None:
        expected_files = {
            "product-brief.md",
            "requirements.md",
            "prioritization.md",
            "architecture-brief.md",
            "decision-log.md",
            "task-breakdown.md",
            "readiness-gate.md",
            "readiness-gate.yaml",
        }
        self.assertEqual(set(ARTIFACT_TEMPLATES), expected_files)

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            created = ensure_agent_workflow_files(root)
            created_names = {path.name for path in created}

            self.assertEqual(created_names, expected_files)
            for filename in expected_files:
                path = root / "docs/agent-workflow" / filename
                self.assertTrue(path.is_file(), filename)
                self.assertTrue(path.read_text(encoding="utf-8").strip(), filename)

    def test_initializer_does_not_overwrite_existing_artifacts(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            artifact_dir = root / "docs/agent-workflow"
            artifact_dir.mkdir(parents=True)
            custom_requirements = artifact_dir / "requirements.md"
            custom_requirements.write_text("custom requirements\n", encoding="utf-8")

            created = ensure_agent_workflow_files(root)

            self.assertNotIn(custom_requirements, created)
            self.assertEqual(custom_requirements.read_text(encoding="utf-8"), "custom requirements\n")
            self.assertIn(artifact_dir / "readiness-gate.yaml", created)


if __name__ == "__main__":
    unittest.main()
