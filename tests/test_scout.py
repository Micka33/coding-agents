from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from coding_agents.scout import _is_sensitive, scout_tools


class ScoutSecretGuardTests(unittest.TestCase):
    def test_sensitive_file_detection_includes_env_keys_and_ssh_private_keys(self) -> None:
        for path in (
            Path(".env"),
            Path(".ENV"),
            Path(".Env.local"),
            Path("config/.ENV/secret.txt"),
            Path("secrets/private.pem"),
            Path("secrets/CERT.PEM"),
            Path("secrets/private.key"),
            Path("secrets/PRIVATE.KEY"),
            Path(".ssh/id_rsa"),
            Path(".ssh/ID_ED25519"),
        ):
            with self.subTest(path=path):
                self.assertTrue(_is_sensitive(path))

        self.assertFalse(_is_sensitive(Path("coding_agents/config.py")))

    def test_scout_tool_list_excludes_execute_and_keeps_reconnaissance_tools(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tool_names = {tool.name for tool in scout_tools(Path(tmp))}

        self.assertNotIn("execute", tool_names)
        self.assertEqual(tool_names, {"ls", "read_file", "glob", "grep"})

    def test_scout_read_file_refuses_sensitive_ssh_private_key(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            private_key = root / ".ssh/id_rsa"
            private_key.parent.mkdir()
            private_key.write_text("secret", encoding="utf-8")
            read_tool = next(tool for tool in scout_tools(root) if tool.name == "read_file")

            result = read_tool.invoke({"path": ".ssh/id_rsa"})

        self.assertIn("error", result)
        self.assertIn("sensitive", result["error"])

    def test_scout_read_file_refuses_case_variant_secret_names(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            env_file = root / ".Env.local"
            env_file.write_text("TOKEN=secret", encoding="utf-8")
            key_file = root / "secrets/PRIVATE.KEY"
            key_file.parent.mkdir()
            key_file.write_text("secret", encoding="utf-8")
            env_dir_file = root / "config/.ENV/secret.txt"
            env_dir_file.parent.mkdir(parents=True)
            env_dir_file.write_text("secret", encoding="utf-8")
            read_tool = next(tool for tool in scout_tools(root) if tool.name == "read_file")

            env_result = read_tool.invoke({"path": ".Env.local"})
            key_result = read_tool.invoke({"path": "secrets/PRIVATE.KEY"})
            env_dir_result = read_tool.invoke({"path": "config/.ENV/secret.txt"})

        self.assertIn("error", env_result)
        self.assertIn("sensitive", env_result["error"])
        self.assertIn("error", key_result)
        self.assertIn("sensitive", key_result["error"])
        self.assertIn("error", env_dir_result)
        self.assertIn("sensitive", env_dir_result["error"])

    def test_scout_grep_refuses_case_variant_sensitive_target(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            env_file = root / ".ENV"
            env_file.write_text("TOKEN=secret", encoding="utf-8")
            grep_tool = next(tool for tool in scout_tools(root) if tool.name == "grep")

            result = grep_tool.invoke({"pattern": "TOKEN", "path": ".ENV"})

        self.assertEqual(len(result), 1)
        self.assertIn("error", result[0])
        self.assertIn("sensitive", result[0]["error"])

    def test_scout_grep_treats_option_like_pattern_as_literal_without_subprocess(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            pattern = "--pre=touch scout-pwned"
            (root / "haystack.txt").write_text(f"literal {pattern}\n", encoding="utf-8")
            side_effect = root / "scout-pwned"
            grep_tool = next(tool for tool in scout_tools(root) if tool.name == "grep")

            with patch("subprocess.run", side_effect=AssertionError("subprocess must not be used")):
                result = grep_tool.invoke({"pattern": pattern})

        self.assertEqual(result, [{"path": "haystack.txt", "line": 1, "text": f"literal {pattern}"}])
        self.assertFalse(side_effect.exists())

    def test_scout_refuses_symlink_alias_to_env_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            env_file = root / ".env"
            env_file.write_text("TOKEN=super-secret", encoding="utf-8")
            alias = root / "public.txt"
            try:
                alias.symlink_to(env_file)
            except OSError as exc:  # pragma: no cover - platform dependent
                self.skipTest(f"symlinks unavailable: {exc}")
            read_tool = next(tool for tool in scout_tools(root) if tool.name == "read_file")
            grep_tool = next(tool for tool in scout_tools(root) if tool.name == "grep")

            read_result = read_tool.invoke({"path": "public.txt"})
            grep_alias_result = grep_tool.invoke({"pattern": "super-secret", "path": "public.txt"})
            grep_result = grep_tool.invoke({"pattern": "super-secret"})

        self.assertIn("error", read_result)
        self.assertIn("symlink", read_result["error"])
        self.assertEqual(len(grep_alias_result), 1)
        self.assertIn("error", grep_alias_result[0])
        self.assertIn("symlink", grep_alias_result[0]["error"])
        self.assertEqual(grep_result, [])


if __name__ == "__main__":
    unittest.main()
