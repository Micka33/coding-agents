from __future__ import annotations

import ast
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from deepagents.backends.protocol import ReadResult

from src.team_instanciator.scoped_read_tools_factory import (
    ScopedReadToolsFactory,
    _ScopedReadToolAdapter,
    create_scoped_read_tools,
)


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

    def test_factory_function_accepts_relative_custom_root_from_context(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "sub").mkdir()

            tools = create_scoped_read_tools(SimpleNamespace(root_dir=root), {"root_dir": "sub"})

        self.assertEqual([tool.name for tool in tools], ["ls", "read_file", "glob", "grep"])

    def test_error_handlers_and_backend_error_results_are_returned_as_text(self) -> None:
        class ErrorBackend:
            def ls(self, path):
                return SimpleNamespace(error="ls failed", entries=None)

            def glob(self, pattern, path="/"):
                return SimpleNamespace(error="glob failed", matches=None)

            def grep(self, pattern, path=None, glob=None):
                return SimpleNamespace(error="grep failed", matches=None)

        with tempfile.TemporaryDirectory() as tmp:
            adapter = _ScopedReadToolAdapter(tmp)
            adapter._backend = ErrorBackend()
            factory = ScopedReadToolsFactory()

            self.assertEqual(adapter.ls("/"), "Error: ls failed")
            self.assertEqual(adapter.glob("*.py"), "Error: glob failed")
            self.assertEqual(adapter.grep("needle"), "grep failed")
            self.assertEqual(factory._handle_tool_error(RuntimeError("boom")), "Error: boom")

    def test_read_result_formatting_handles_missing_binary_empty_line_and_token_truncation(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            adapter = _ScopedReadToolAdapter(tmp, tool_token_limit=None)

            self.assertEqual(adapter._format_read_result(ReadResult(file_data=None), "/missing.txt", 0, 10), "Error: no data returned for '/missing.txt'")
            self.assertEqual(adapter._format_read_result(ReadResult(file_data={"content": "binary"}), "/image.png", 0, 10), "binary")
            self.assertIn("empty", adapter._format_read_result(ReadResult(file_data={"content": ""}), "/empty.txt", 0, 10).lower())
            self.assertEqual(adapter._truncate_read_content("1\n2\n3\n", "/limited.txt", 2), "1\n2\n")
            token_limited_adapter = _ScopedReadToolAdapter(tmp, tool_token_limit=1)
            self.assertIn("truncated", token_limited_adapter._truncate_read_content("x" * 100, "/tokens.txt", 100).lower())

    def _tools(self, root: Path):
        return {tool.name: tool for tool in ScopedReadToolsFactory().create(root)}


if __name__ == "__main__":
    unittest.main()
