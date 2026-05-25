from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from deepagents.middleware.filesystem import _check_fs_permission

from coding_agents.permissions import filesystem_permissions


class FilesystemPermissionsTests(unittest.TestCase):
    def test_shaping_allows_reads_and_only_workflow_artifact_writes(self) -> None:
        permissions = filesystem_permissions("shaping", "docs/agent-workflow")

        self.assertEqual(_check_fs_permission(permissions, "read", "/coding_agents/config.py"), "allow")
        self.assertEqual(
            _check_fs_permission(permissions, "write", "/docs/agent-workflow/readiness-gate.yaml"),
            "deny",
        )
        self.assertEqual(
            _check_fs_permission(permissions, "write", "/docs/agent-workflow/READINESS-GATE.YAML"),
            "deny",
        )
        self.assertEqual(
            _check_fs_permission(permissions, "write", "/docs/agent-workflow/readiness-gate.md"),
            "allow",
        )
        self.assertEqual(
            _check_fs_permission(permissions, "write", "/docs/agent-workflow/new-artifact.md"),
            "deny",
        )
        self.assertEqual(
            _check_fs_permission(permissions, "write", "/coding_agents/config.py"),
            "deny",
        )
        self.assertFalse(
            any(
                rule.mode == "allow"
                and "write" in rule.operations
                and "/docs/agent-workflow/**" in rule.paths
                for rule in permissions
            )
        )

    def test_implementation_without_write_paths_allows_repo_wide_writes_except_protected_paths(self) -> None:
        permissions = filesystem_permissions("implementation")

        self.assertEqual(_check_fs_permission(permissions, "read", "/coding_agents/config.py"), "allow")
        self.assertEqual(
            _check_fs_permission(permissions, "write", "/docs/agent-workflow/readiness-gate.yaml"),
            "deny",
        )
        self.assertEqual(
            _check_fs_permission(permissions, "write", "/docs/agent-workflow/READINESS-GATE.YAML"),
            "deny",
        )
        self.assertEqual(
            _check_fs_permission(permissions, "write", "/docs/agent-workflow/readiness-gate.md"),
            "allow",
        )
        self.assertEqual(
            _check_fs_permission(permissions, "write", "/coding_agents/config.py"),
            "allow",
        )
        self.assertEqual(
            _check_fs_permission(permissions, "write", "/.env"),
            "deny",
        )
        self.assertEqual(
            _check_fs_permission(permissions, "write", "/service/private.key"),
            "deny",
        )
        self.assertTrue(
            any(
                rule.mode == "allow" and "write" in rule.operations and "/**" in rule.paths
                for rule in permissions
            )
        )

    def test_implementation_write_paths_are_task_scoped_and_normalized(self) -> None:
        permissions = filesystem_permissions(
            "implementation",
            implementation_write_paths=("coding_agents/config.py", "tests/"),
        )

        self.assertEqual(
            _check_fs_permission(permissions, "write", "/coding_agents/config.py"),
            "allow",
        )
        self.assertEqual(_check_fs_permission(permissions, "write", "/tests"), "allow")
        self.assertEqual(
            _check_fs_permission(permissions, "write", "/tests/test_readiness.py"),
            "allow",
        )
        self.assertEqual(
            _check_fs_permission(permissions, "write", "/coding_agents/team.py"),
            "deny",
        )
        self.assertEqual(_check_fs_permission(permissions, "write", "/README.md"), "deny")

        write_allow = [
            rule for rule in permissions if rule.mode == "allow" and "write" in rule.operations
        ]
        self.assertEqual(len(write_allow), 1)
        self.assertEqual(
            write_allow[0].paths,
            ["/coding_agents/config.py", "/tests", "/tests/**"],
        )
        self.assertEqual(permissions[-1].mode, "deny")
        self.assertEqual(permissions[-1].paths, ["/**"])

    def test_protected_write_denies_win_over_implementation_allowlists(self) -> None:
        permissions = filesystem_permissions(
            "implementation",
            implementation_write_paths=(
                "docs/agent-workflow/readiness-gate.yaml",
                "docs/agent-workflow/READINESS-GATE.YAML",
                ".env",
            ),
        )

        self.assertEqual(
            _check_fs_permission(permissions, "write", "/docs/agent-workflow/readiness-gate.yaml"),
            "deny",
        )
        self.assertEqual(
            _check_fs_permission(permissions, "write", "/docs/agent-workflow/READINESS-GATE.YAML"),
            "deny",
        )
        self.assertEqual(_check_fs_permission(permissions, "write", "/.env"), "deny")

        directory_permissions = filesystem_permissions(
            "implementation",
            implementation_write_paths=("docs/agent-workflow/",),
        )
        self.assertEqual(
            _check_fs_permission(directory_permissions, "write", "/docs/agent-workflow/READINESS-GATE.YAML"),
            "deny",
        )

    def test_secret_like_paths_are_read_denied_before_broad_read_allow(self) -> None:
        permissions = filesystem_permissions("shaping", "docs/agent-workflow")

        for path in (
            "/.env",
            "/.ENV",
            "/.env.local",
            "/.Env.local",
            "/service/.env",
            "/service/.ENV.production",
            "/service/.ENV/secret.txt",
            "/cert.pem",
            "/CERT.PEM",
            "/service/key.pem",
            "/service/KEY.PEM",
            "/service/private.key",
            "/service/PRIVATE.KEY",
            "/service/cert.P12",
            "/service/cert.PFX",
            "/service/id_rsa",
            "/service/ID_RSA",
            "/service/id_ed25519",
            "/service/ID_ED25519",
        ):
            with self.subTest(path=path):
                self.assertEqual(_check_fs_permission(permissions, "read", path), "deny")

        self.assertEqual(_check_fs_permission(permissions, "read", "/coding_agents/config.py"), "allow")

    def test_empty_implementation_write_path_is_invalid(self) -> None:
        with self.assertRaisesRegex(ValueError, "must not be empty"):
            filesystem_permissions("implementation", implementation_write_paths=("",))

    def test_repo_wide_implementation_write_path_is_invalid(self) -> None:
        for path in ("/**", "/", ".", "./", "*", "*/", "/*", "**/*"):
            with self.subTest(path=path):
                with self.assertRaisesRegex(ValueError, "omit --write-path"):
                    filesystem_permissions("implementation", implementation_write_paths=(path,))

    def test_glob_and_traversal_implementation_write_paths_are_invalid(self) -> None:
        invalid_paths = (
            "/**/*.py",
            "coding_agents/*.py",
            "coding_agents/?.py",
            "coding_agents/[abc].py",
            "coding_agents/{a,b}.py",
            "coding_agents/!secret.py",
            "../outside.py",
            "coding_agents/../README.md",
            "/tmp/outside.py",
        )

        for path in invalid_paths:
            with self.subTest(path=path):
                with self.assertRaises(ValueError):
                    filesystem_permissions("implementation", implementation_write_paths=(path,))

    def test_implementation_write_paths_reject_symlink_aliases_with_root_validation(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "repo"
            outside = Path(tmp) / "outside"
            root.mkdir()
            outside.mkdir()
            (outside / "secret.py").write_text("secret", encoding="utf-8")
            try:
                (root / "linked.py").symlink_to(outside / "secret.py")
                (root / "linked-dir").symlink_to(outside, target_is_directory=True)
            except OSError as exc:  # pragma: no cover - platform dependent
                self.skipTest(f"symlinks unavailable: {exc}")

            for path in ("linked.py", "linked-dir/new.py", "linked-dir/"):
                with self.subTest(path=path):
                    with self.assertRaisesRegex(ValueError, "symlink"):
                        filesystem_permissions(
                            "implementation",
                            implementation_write_paths=(path,),
                            root_dir=root,
                        )

    def test_implementation_directory_scope_requires_existing_non_symlink_directory(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)

            with self.assertRaisesRegex(ValueError, "existing non-symlink directory"):
                filesystem_permissions(
                    "implementation",
                    implementation_write_paths=("missing/",),
                    root_dir=root,
                )

    def test_implementation_write_paths_reject_existing_file_as_parent_component(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "not_a_dir").write_text("content", encoding="utf-8")

            with self.assertRaisesRegex(ValueError, "parent components"):
                filesystem_permissions(
                    "implementation",
                    implementation_write_paths=("not_a_dir/new_file.py",),
                    root_dir=root,
                )

    def test_implementation_exact_new_file_validates_existing_parent_under_root(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "src").mkdir()

            permissions = filesystem_permissions(
                "implementation",
                implementation_write_paths=("src/new_file.py",),
                root_dir=root,
            )

        self.assertEqual(_check_fs_permission(permissions, "write", "/src/new_file.py"), "allow")


if __name__ == "__main__":
    unittest.main()
