from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from deepagents.middleware.filesystem import supports_execution

from coding_agents.safe_filesystem import SafeFilesystemBackend, SafeLocalShellBackend


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
            root = Path(tmp).resolve()
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

    def test_local_shell_backend_supports_execute_and_keeps_safe_filesystem(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            secret = root / ".env"
            secret.write_text("TOKEN=secret\n", encoding="utf-8")
            backend = SafeLocalShellBackend(root_dir=root, virtual_mode=True)

            execute_result = backend.execute("printf local-ok")
            read_result = backend.read("/.env")

        self.assertTrue(supports_execution(backend))
        self.assertEqual(execute_result.exit_code, 0)
        self.assertEqual(execute_result.output, "local-ok")
        self.assertIsNotNone(read_result.error)
        self.assertIn("sensitive", read_result.error)

    def test_filesystem_backend_rejects_common_secret_like_filenames(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "credentials.json").write_text("secret", encoding="utf-8")
            (root / ".npmrc").write_text("//registry/:_authToken=secret", encoding="utf-8")
            backend = SafeFilesystemBackend(root_dir=root, virtual_mode=True)

            credentials_result = backend.read("/credentials.json")
            npmrc_result = backend.read("/.npmrc")
            entries = backend.ls("/").entries or []
            grep_matches = backend.grep("secret", path="/").matches or []

        self.assertIsNotNone(credentials_result.error)
        self.assertIn("sensitive", credentials_result.error)
        self.assertIsNotNone(npmrc_result.error)
        self.assertIn("sensitive", npmrc_result.error)
        self.assertNotIn("/credentials.json", [entry["path"] for entry in entries])
        self.assertNotIn("/.npmrc", [entry["path"] for entry in entries])
        self.assertEqual(grep_matches, [])

    def test_local_shell_execute_output_redacts_common_secret_shapes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            backend = SafeLocalShellBackend(
                root_dir=Path(tmp),
                virtual_mode=True,
                env={"TOKEN": "super-secret-token"},
                inherit_env=False,
            )

            result = backend.execute(
                "printf 'api_key=abc123 token=%s postgres://user:pass@host/db "
                "api_key: sk-yaml \"x-api-key\": \"sk-json\" "
                "PRIVATE_KEY=inline-key Authorization: Bearer bearer-secret "
                "AWS_ACCESS_KEY_ID=AKIA_TEST' \"$TOKEN\""
            )

        self.assertEqual(result.exit_code, 0)
        self.assertIn("api_key=<redacted>", result.output)
        self.assertIn("token=<redacted>", result.output)
        self.assertIn("postgres://***:***@host/db", result.output)
        self.assertIn("api_key: <redacted>", result.output)
        self.assertIn('"x-api-key": "<redacted>"', result.output)
        self.assertIn("PRIVATE_KEY=<redacted>", result.output)
        self.assertIn("Authorization: Bearer <redacted>", result.output)
        self.assertIn("AWS_ACCESS_KEY_ID=<redacted>", result.output)
        for secret in (
            "abc123",
            "super-secret-token",
            "user:pass",
            "sk-yaml",
            "sk-json",
            "inline-key",
            "bearer-secret",
            "AKIA_TEST",
        ):
            self.assertNotIn(secret, result.output)


if __name__ == "__main__":
    unittest.main()
