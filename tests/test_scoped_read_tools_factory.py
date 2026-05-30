from __future__ import annotations

import ast
import tempfile
import unittest
from pathlib import Path

from src.team_instanciator.scoped_read_tools_factory import ScopedReadToolsFactory


class ScopedReadToolsFactoryTests(unittest.TestCase):
    def test_successful_tool_calls_match_deepagents_result_shapes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "notes.txt").write_text("alpha\nneedle\n", encoding="utf-8")
            package = root / "pkg"
            package.mkdir()
            (package / "app.py").write_text("print('needle')\n", encoding="utf-8")
            tools = self._tools(root)

            ls_result = tools["ls"].invoke({"path": "/"})
            read_result = tools["read_file"].invoke({"file_path": "/notes.txt", "offset": 1, "limit": 10})
            glob_result = tools["glob"].invoke({"pattern": "**/*.py"})
            grep_result = tools["grep"].invoke({"pattern": "needle", "output_mode": "content"})

        self.assertEqual(ast.literal_eval(ls_result), ["/notes.txt", "/pkg/"])
        self.assertEqual(read_result, "     2\tneedle")
        self.assertEqual(ast.literal_eval(glob_result), ["/pkg/app.py"])
        self.assertEqual(grep_result, "/notes.txt:\n  2: needle\n/pkg/app.py:\n  1: print('needle')")

    def test_missing_paths_match_deepagents_empty_or_error_results(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tools = self._tools(Path(tmp))

            ls_result = tools["ls"].invoke({"path": "/tmp_check"})
            read_result = tools["read_file"].invoke({"file_path": "/tmp_check"})
            grep_result = tools["grep"].invoke({"pattern": "needle", "path": "/tmp_check"})

        self.assertEqual(ast.literal_eval(ls_result), [])
        self.assertIn("Error:", read_result)
        self.assertIn("not found", read_result)
        self.assertEqual(grep_result, "No matches found")

    def test_out_of_scope_paths_return_errors_instead_of_raising(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "repo"
            root.mkdir()
            outside = Path(tmp) / "outside.txt"
            outside.write_text("outside", encoding="utf-8")
            tools = self._tools(root)

            read_result = tools["read_file"].invoke({"file_path": "../outside.txt"})
            grep_result = tools["grep"].invoke({"pattern": "outside", "path": "../outside.txt"})
            glob_result = tools["glob"].invoke({"pattern": "../*.txt"})

        self.assertIn("Error:", read_result)
        self.assertIn("Path traversal", read_result)
        self.assertIn("Error:", grep_result)
        self.assertIn("Path traversal", grep_result)
        self.assertIn("Error:", glob_result)
        self.assertIn("Path traversal", glob_result)

    def test_wrong_path_kinds_match_deepagents_empty_or_error_results(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "file.txt").write_text("content", encoding="utf-8")
            (root / "dir").mkdir()
            tools = self._tools(root)

            ls_result = tools["ls"].invoke({"path": "/file.txt"})
            read_result = tools["read_file"].invoke({"file_path": "/dir"})

        self.assertEqual(ast.literal_eval(ls_result), [])
        self.assertIn("Error:", read_result)
        self.assertIn("not found", read_result)

    def test_grep_results_are_truncated_like_deepagents_tools(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "large.txt").write_text("needle " + ("x" * 90_000), encoding="utf-8")
            tools = self._tools(root)

            result = tools["grep"].invoke({"pattern": "needle", "output_mode": "content"})

        self.assertIn("results truncated", result)

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
