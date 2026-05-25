from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from coding_agents.safe_filesystem import SafeFilesystemBackend


class SafeFilesystemBackendTests(unittest.TestCase):
    def test_regular_read_write_edit_grep_and_glob_still_work(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "src").mkdir()
            (root / "src/app.py").write_text("print('hello')\n", encoding="utf-8")
            backend = SafeFilesystemBackend(root_dir=root, virtual_mode=True)

            read_result = backend.read("/src/app.py")
            grep_result = backend.grep("hello", path="/src")
            glob_result = backend.glob("**/*.py", path="/")
            write_result = backend.write("/src/new.py", "value = 1\n")
            edit_result = backend.edit("/src/new.py", "value = 1", "value = 2")

        self.assertIsNone(read_result.error)
        self.assertIsNotNone(read_result.file_data)
        self.assertEqual(grep_result.error, None)
        self.assertEqual(grep_result.matches, [{"path": "/src/app.py", "line": 1, "text": "print('hello')"}])
        self.assertEqual([match["path"] for match in glob_result.matches or []], ["/src/app.py"])
        self.assertEqual(write_result.error, None)
        self.assertEqual(edit_result.error, None)

    def test_rejects_file_symlink_alias_to_readiness_gate_for_read_write_and_edit(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            gate = root / "docs/agent-workflow/readiness-gate.yaml"
            gate.parent.mkdir(parents=True)
            gate.write_text("approved: false\n", encoding="utf-8")
            allowed_dir = root / "implementation"
            allowed_dir.mkdir()
            alias = allowed_dir / "gate-alias.yaml"
            try:
                alias.symlink_to(gate)
            except OSError as exc:  # pragma: no cover - platform dependent
                self.skipTest(f"symlinks unavailable: {exc}")
            backend = SafeFilesystemBackend(root_dir=root, virtual_mode=True)

            read_result = backend.read("/implementation/gate-alias.yaml")
            write_result = backend.write("/implementation/gate-alias.yaml", "approved: true\n")
            edit_result = backend.edit("/implementation/gate-alias.yaml", "false", "true")

        for result in (read_result, write_result, edit_result):
            self.assertIsNotNone(result.error)
            self.assertIn("symlink", result.error)
        self.assertEqual(gate.read_text(encoding="utf-8"), "approved: false\n")

    def test_rejects_directory_symlink_descendant_inside_allowed_directory(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            gate = root / "docs/agent-workflow/readiness-gate.yaml"
            gate.parent.mkdir(parents=True)
            gate.write_text("approved: false\n", encoding="utf-8")
            allowed_dir = root / "implementation"
            allowed_dir.mkdir()
            link_dir = allowed_dir / "workflow-link"
            try:
                link_dir.symlink_to(gate.parent, target_is_directory=True)
            except OSError as exc:  # pragma: no cover - platform dependent
                self.skipTest(f"symlinks unavailable: {exc}")
            backend = SafeFilesystemBackend(root_dir=root, virtual_mode=True)

            read_result = backend.read("/implementation/workflow-link/readiness-gate.yaml")
            grep_result = backend.grep("approved", path="/implementation/workflow-link")
            glob_result = backend.glob("**/*.yaml", path="/implementation/workflow-link")

        self.assertIsNotNone(read_result.error)
        self.assertIn("symlink", read_result.error)
        self.assertIsNotNone(grep_result.error)
        self.assertIn("symlink", grep_result.error)
        self.assertIsNotNone(glob_result.error)
        self.assertIn("symlink", glob_result.error)

    def test_ls_glob_and_grep_skip_symlink_alias_to_env_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "repo"
            outside = Path(tmp) / "outside"
            root.mkdir()
            outside.mkdir()
            env_file = outside / ".env"
            env_file.write_text("TOKEN=super-secret\n", encoding="utf-8")
            (root / "safe.txt").write_text("TOKEN=public\n", encoding="utf-8")
            alias = root / "public.env"
            try:
                alias.symlink_to(env_file)
            except OSError as exc:  # pragma: no cover - platform dependent
                self.skipTest(f"symlinks unavailable: {exc}")
            backend = SafeFilesystemBackend(root_dir=root, virtual_mode=True)

            entries = backend.ls("/").entries or []
            glob_matches = backend.glob("*.env", path="/").matches or []
            grep_matches = backend.grep("super-secret", path="/").matches or []

        self.assertNotIn("/public.env", [entry["path"] for entry in entries])
        self.assertEqual(glob_matches, [])
        self.assertEqual(grep_matches, [])


if __name__ == "__main__":
    unittest.main()
