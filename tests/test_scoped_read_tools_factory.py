from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from coding_agents.team_instanciator.scoped_read_tools_factory import ScopedReadToolsFactory


class ScopedReadToolsFactoryTests(unittest.TestCase):
    def test_successful_tool_calls_keep_existing_result_shapes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "notes.txt").write_text("alpha\nneedle\n", encoding="utf-8")
            package = root / "pkg"
            package.mkdir()
            (package / "app.py").write_text("print('needle')\n", encoding="utf-8")
            tools = self._tools(root)

            ls_result = tools["ls"].invoke({"path": "."})
            read_result = tools["read_file"].invoke({"path": "notes.txt", "start_line": 2})
            glob_result = tools["glob"].invoke({"pattern": "**/*.py"})
            grep_result = tools["grep"].invoke({"pattern": "needle"})

        self.assertEqual(ls_result, ["notes.txt", "pkg"])
        self.assertEqual(read_result, "needle")
        self.assertEqual(glob_result, ["pkg/app.py"])
        self.assertEqual(grep_result, ["notes.txt:2:needle", "pkg/app.py:1:print('needle')"])

    def test_missing_paths_return_errors_instead_of_raising(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tools = self._tools(Path(tmp))

            ls_result = tools["ls"].invoke({"path": "/tmp_check"})
            read_result = tools["read_file"].invoke({"path": "/tmp_check"})
            grep_result = tools["grep"].invoke({"pattern": "needle", "path": "/tmp_check"})

        self.assertEqual(len(ls_result), 1)
        self.assertIn("Error:", ls_result[0])
        self.assertIn("path does not exist", ls_result[0])
        self.assertIn("Error:", read_result)
        self.assertIn("path does not exist", read_result)
        self.assertEqual(len(grep_result), 1)
        self.assertIn("Error:", grep_result[0])
        self.assertIn("path does not exist", grep_result[0])

    def test_out_of_scope_paths_return_errors_instead_of_raising(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "repo"
            root.mkdir()
            outside = Path(tmp) / "outside.txt"
            outside.write_text("outside", encoding="utf-8")
            tools = self._tools(root)

            read_result = tools["read_file"].invoke({"path": "../outside.txt"})
            grep_result = tools["grep"].invoke({"pattern": "outside", "path": "../outside.txt"})
            glob_result = tools["glob"].invoke({"pattern": "../*.txt"})

        self.assertIn("Error:", read_result)
        self.assertIn("outside root", read_result)
        self.assertEqual(len(grep_result), 1)
        self.assertIn("Error:", grep_result[0])
        self.assertIn("outside root", grep_result[0])
        self.assertEqual(len(glob_result), 1)
        self.assertIn("Error:", glob_result[0])
        self.assertIn("Path traversal", glob_result[0])

    def test_wrong_path_kinds_return_errors_instead_of_raising(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "file.txt").write_text("content", encoding="utf-8")
            (root / "dir").mkdir()
            tools = self._tools(root)

            ls_result = tools["ls"].invoke({"path": "file.txt"})
            read_result = tools["read_file"].invoke({"path": "dir"})

        self.assertEqual(len(ls_result), 1)
        self.assertIn("Error:", ls_result[0])
        self.assertIn("not a directory", ls_result[0])
        self.assertIn("Error:", read_result)
        self.assertIn("not a file", read_result)

    def test_invalid_tool_inputs_return_errors_instead_of_raising(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tools = self._tools(Path(tmp))

            result = tools["grep"].invoke({})

        self.assertIn("Error:", result)
        self.assertIn("Invalid tool input", result)

    def _tools(self, root: Path):
        return {tool.name: tool for tool in ScopedReadToolsFactory().create(root)}


if __name__ == "__main__":
    unittest.main()
