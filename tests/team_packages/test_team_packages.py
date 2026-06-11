from __future__ import annotations

from contextlib import contextmanager
import io
import json
import os
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
import shutil
import subprocess
import tempfile
import unittest

from src.team_instanciator.configuration.runtime_configuration import RuntimeConfiguration
from src.team_instanciator.core.team_instanciator import TeamInstanciator
from src.team_instanciator.errors.team_instanciator_error import TeamInstanciatorError
from src.team_instanciator.resolvers.skill_source_resolver import SkillSourceResolver
from src.team_packages.cli import TeamPackageCli
from src.team_packages.content_hasher import ContentHasher
from src.team_packages.installer import TeamPackageInstaller
from src.team_packages.locked_package import LockedPackage
from src.team_packages.lockfile_store import TeamLockfileStore
from src.team_packages.package_error import TeamPackageError
from src.team_packages.package_locator import InstalledPackageLocator
from src.team_packages.package_manifest import PackageManifest
from src.team_packages.package_manifest_loader import PackageManifestLoader
from src.team_packages.package_validator import TeamPackageValidator
from src.team_packages.risk_scanner import PackageRiskScanner
from src.team_packages.trust_store import TeamPackageTrustStore
from src.team_packages import version as version_module
from src.webapp_studio.backend.api.team_discovery_service import TeamDiscoveryService
from tests.support import agent, defaults, team


class TeamPackageTests(unittest.TestCase):
    def test_validator_accepts_external_skills_and_reports_missing_warnings(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            workspace = root / "workspace"
            package = root / "pkg"
            workspace.mkdir()
            self._write_package(
                package,
                manifest_extra=[
                    "skills:",
                    "  external:",
                    "    - id: company-private-docs",
                    "      install_hint: npx skills add acme/agent-skills",
                    "requires:",
                    "  env:",
                    "    - COMPANY_DOCS_MCP_TOKEN",
                ],
                frontmatter_extra=[
                    "skills:",
                    "  only:",
                    "    - bundled",
                    "    - company-private-docs",
                ],
            )
            (package / "teams" / "software" / "skills" / "bundled").mkdir(parents=True)
            (package / "teams" / "software" / "skills" / "bundled" / "SKILL.md").write_text("bundled", encoding="utf-8")

            with working_directory(workspace), patch.dict(os.environ, {"CODEX_HOME": ""}):
                manifest, warnings, teams = TeamPackageValidator().validate(package)
                (workspace / ".agents" / "skills" / "company-private-docs").mkdir(parents=True)
                (workspace / ".agents" / "skills" / "company-private-docs" / "SKILL.md").write_text("external", encoding="utf-8")
                _manifest, installed_warnings, _teams = TeamPackageValidator().validate(package)

            codex_home = root / "codex-home"
            (codex_home / "skills" / "company-private-docs").mkdir(parents=True)
            (codex_home / "skills" / "company-private-docs" / "SKILL.md").write_text("external", encoding="utf-8")
            with working_directory(workspace), patch.dict(os.environ, {"CODEX_HOME": str(codex_home)}):
                _manifest, user_warnings, _teams = TeamPackageValidator().validate(package)

        self.assertEqual(manifest.name, "acme/software-team")
        self.assertEqual([item.id for item in teams], ["software"])
        self.assertTrue(any("company-private-docs" in warning for warning in warnings))
        self.assertFalse(any("company-private-docs" in warning for warning in installed_warnings))
        self.assertFalse(any("company-private-docs" in warning for warning in user_warnings))
        self.assertTrue(any("COMPANY_DOCS_MCP_TOKEN" in warning for warning in warnings))

    def test_local_install_writes_lockfile_and_trust_gate_uses_local_store(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            workspace = root / "workspace"
            codex_home = root / "codex-home"
            package = root / "pkg"
            workspace.mkdir()
            self._write_package(
                package,
                team_extra=[
                    "defaults:",
                    "  execution_backend:",
                    "    default: local",
                    "toolsets:",
                    "  shell:",
                    "    - shell",
                ],
                frontmatter_extra=[
                    "toolsets:",
                    "  - shell",
                ],
            )

            with working_directory(workspace):
                entry, warnings = TeamPackageInstaller().install(str(package))
                lockfile = json.loads((workspace / ".coding-agents" / "team-lock.json").read_text(encoding="utf-8"))

            installed_team = workspace / ".coding-agents" / "packages" / "acme" / "software-team" / "teams" / "software" / "team.yaml"
            risky_team = team(
                team_id="software",
                load_cwd=workspace,
                path=installed_team,
                team_defaults=defaults(execution_backend_default="local"),
                agents={"entry": agent("entry", entrypoint=True, toolsets=("shell",))},
            )
            instanciator = TeamInstanciator(team_loader=SimpleNamespace(load=lambda _path, _variables=None: risky_team))

            self.assertEqual(warnings, [])
            self.assertEqual(entry.risk_flags, ("shell",))
            self.assertEqual(lockfile["packages"][0]["installed_path"], ".coding-agents/packages/acme/software-team")
            self.assertFalse(Path(lockfile["packages"][0]["installed_path"]).is_absolute())
            with patch.dict(os.environ, {"CODEX_HOME": str(codex_home)}):
                # Lockfile risk flags are advisory: clearing them must not bypass the gate.
                TeamLockfileStore(workspace).upsert_package(dict(entry.raw, risk_flags=[]))
                with self.assertRaisesRegex(TeamInstanciatorError, "team trust acme/software-team"):
                    instanciator._enforce_package_trust(risky_team)

                TeamPackageTrustStore().trust("acme/software-team", entry.integrity)
                instanciator._enforce_package_trust(risky_team)

                tampered = installed_team.parent / "tampered.txt"
                tampered.write_text("tampered", encoding="utf-8")
                with self.assertRaisesRegex(TeamInstanciatorError, "does not match its locked integrity"):
                    instanciator._enforce_package_trust(risky_team)
                tampered.unlink()

                no_risk_team = team(team_id="software", load_cwd=workspace, path=installed_team)
                instanciator._enforce_package_trust(no_risk_team)

                unlocked_path = workspace / ".coding-agents" / "packages" / "loose" / "team.yaml"
                unlocked_path.parent.mkdir(parents=True)
                unlocked_path.write_text("", encoding="utf-8")
                with self.assertRaisesRegex(TeamInstanciatorError, "not locked"):
                    instanciator._enforce_package_trust(team(team_id="loose", load_cwd=workspace, path=unlocked_path))
                instanciator._enforce_package_trust(team(team_id="local", load_cwd=workspace, path=workspace / "local-team.yaml"))

    def test_package_skill_layer_is_restricted_to_locked_dependency_ids(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp)
            package_team = workspace / ".coding-agents" / "packages" / "acme" / "software-team" / "teams" / "software" / "team.yaml"
            package_team.parent.mkdir(parents=True)
            package_team.write_text("id: software\n", encoding="utf-8")
            skills_dir = workspace / ".coding-agents" / "skills"
            (skills_dir / "locked").mkdir(parents=True)
            (skills_dir / "locked" / "SKILL.md").write_text("locked", encoding="utf-8")
            (skills_dir / "hidden").mkdir()
            (skills_dir / "hidden" / "SKILL.md").write_text("hidden", encoding="utf-8")
            TeamLockfileStore(workspace).upsert_package(
                {
                    "name": "acme/software-team",
                    "version": "1.0.0",
                    "source": "pkg",
                    "requested": None,
                    "resolved": "sha256-test",
                    "integrity": "sha256-test",
                    "installed_path": ".coding-agents/packages/acme/software-team",
                    "teams": [{"id": "software", "path": "teams/software/team.yaml"}],
                    "risk_flags": [],
                    "dependencies": {
                        "skills": [
                            {
                                "id": "locked",
                                "installed_path": ".coding-agents/skills/locked",
                            }
                        ]
                    },
                }
            )
            loaded_team = team(
                team_id="software",
                load_cwd=workspace,
                path=package_team,
                agents={"entry": agent("entry", entrypoint=True, skills=["locked"])},
            )

            sources = SkillSourceResolver(RuntimeConfiguration({"CODEX_HOME": ""})).resolve_agent_sources(
                loaded_team,
                loaded_team.agents["entry"],
            )

            self.assertEqual([(source.virtual_path, source.label) for source in sources], [("/skills/entry/package", "Package")])
            self.assertEqual(sources[0].allowed_skill_ids, ("locked",))

            inherited_agent = agent("entry", entrypoint=True, skills="inherit")
            inherited_team = team(
                team_id="software",
                load_cwd=workspace,
                path=package_team,
                agents={"entry": inherited_agent},
            )
            permissions = SkillSourceResolver(RuntimeConfiguration({"CODEX_HOME": ""})).read_permission_paths(
                inherited_team,
                inherited_agent,
            )
            self.assertEqual(permissions, ["/skills/package/locked", "/skills/package/locked/**"])

            # A skill that exists in the shared store but is not locked by this
            # package must only be served through layers that legitimately
            # provide it, never through the package source.
            (workspace / ".agents" / "skills" / "hidden").mkdir(parents=True)
            (workspace / ".agents" / "skills" / "hidden" / "SKILL.md").write_text("hidden", encoding="utf-8")
            leak_agent = agent("entry", entrypoint=True, skills=["hidden", "locked"])
            leak_team = team(
                team_id="software",
                load_cwd=workspace,
                path=package_team,
                agents={"entry": leak_agent},
            )
            resolver = SkillSourceResolver(RuntimeConfiguration({"CODEX_HOME": ""}))
            leak_sources = resolver.resolve_agent_sources(leak_team, leak_agent)
            self.assertEqual(
                {source.label: source.allowed_skill_ids for source in leak_sources},
                {"Project": ("hidden", "locked"), "Package": ("locked",)},
            )
            self.assertEqual(
                resolver.read_permission_paths(leak_team, leak_agent),
                [
                    "/skills/entry/project/hidden",
                    "/skills/entry/project/hidden/**",
                    "/skills/entry/package/locked",
                    "/skills/entry/package/locked/**",
                ],
            )

            shutil.rmtree(workspace / ".coding-agents" / "skills")
            remaining = SkillSourceResolver(RuntimeConfiguration({"CODEX_HOME": ""})).resolve_team_sources(inherited_team)
            self.assertEqual([source.label for source in remaining], ["Project"])

    def test_studio_discovers_package_exports_from_lockfile_and_keeps_non_colliding_duplicates(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            workspace = root / "workspace"
            repository = root / "repo"
            workspace.mkdir()
            package_team = workspace / ".coding-agents" / "packages" / "acme" / "software-team" / "teams" / "software" / "team.yaml"
            self._write_discovery_team(package_team, "software")
            self._write_discovery_team(workspace / ".coding-agents" / "teams" / "local" / "team.yaml", "duplicate")
            self._write_discovery_team(repository / "teams" / "builtin" / "team.yaml", "DUPLICATE")
            TeamLockfileStore(workspace).upsert_package(
                {
                    "name": "acme/software-team",
                    "version": "1.0.0",
                    "source": "pkg",
                    "requested": None,
                    "resolved": "sha256-test",
                    "integrity": "sha256-test",
                    "installed_path": ".coding-agents/packages/acme/software-team",
                    "teams": [{"id": "renamed-in-lockfile", "path": "teams/software/team.yaml"}],
                    "risk_flags": [],
                    "requires": {"env": ["PACKAGE_TOKEN"]},
                    "dependencies": {"skills": []},
                }
            )

            with patch.dict(os.environ, {"CODEX_HOME": str(root / "codex-home")}):
                discovery = TeamDiscoveryService(repository_root=repository, workspace_dir=workspace).discover()

        self.assertEqual(discovery["status"], "ready")
        self.assertEqual([team["team_id"] for team in discovery["teams"]], ["software"])
        self.assertEqual(discovery["teams"][0]["source"], "package")
        self.assertEqual(discovery["teams"][0]["package_name"], "acme/software-team")
        self.assertEqual(discovery["teams"][0]["lock_status"], "locked")
        self.assertEqual(discovery["teams"][0]["trust_status"], "not_required")
        self.assertEqual(discovery["teams"][0]["missing_required_env"], ["PACKAGE_TOKEN"])
        self.assertEqual(discovery["duplicate_ids"][0]["normalized_id"], "duplicate")

    def test_cli_commands_cover_package_lifecycle_and_errors(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            workspace = root / "workspace"
            package = root / "pkg"
            workspace.mkdir()
            self._write_package(package)
            output = io.StringIO()
            errors = io.StringIO()

            with (
                working_directory(workspace),
                patch.dict(os.environ, {"CODEX_HOME": str(root / "codex-home")}),
                patch("sys.stdout", output),
                patch("sys.stderr", errors),
            ):
                self.assertEqual(TeamPackageCli().main(["list"]), 0)
                self.assertEqual(TeamPackageCli().main(["validate", str(package)]), 0)
                self.assertEqual(TeamPackageCli().main(["install", str(package)]), 0)
                self.assertEqual(TeamPackageCli().main(["list"]), 0)
                self.assertEqual(TeamPackageCli().main(["trust", "acme/software-team"]), 0)
                self.assertEqual(TeamPackageCli().main(["update", "acme/software-team"]), 0)
                self.assertEqual(TeamPackageCli().main(["uninstall", "acme/software-team"]), 0)
                self.assertEqual(TeamPackageCli().main(["update"]), 0)
                self.assertEqual(TeamPackageCli().main(["trust", "missing/package"]), 1)
                with patch.object(TeamPackageValidator, "validate", side_effect=OSError("validate blew up")):
                    self.assertEqual(TeamPackageCli().main(["validate", str(package)]), 1)
                TeamPackageCli()._print_warnings(["watch this"])
                with self.assertRaisesRegex(TeamPackageError, "Unsupported"):
                    TeamPackageCli()._dispatch(SimpleNamespace(command="unknown"))

        text = output.getvalue()
        self.assertIn("Package valid: acme/software-team@1.0.0", text)
        self.assertIn("Installed acme/software-team@1.0.0", text)
        self.assertIn("team software -> teams/software/team.yaml", text)
        self.assertIn("Trusted acme/software-team", text)
        self.assertIn("Updated acme/software-team@1.0.0", text)
        self.assertIn("Uninstalled acme/software-team", text)
        self.assertIn("No packages installed.", text)
        self.assertIn("Package is not installed: missing/package", errors.getvalue())
        self.assertIn("validate blew up", errors.getvalue())
        self.assertIn("warning: watch this", errors.getvalue())

    def test_git_package_and_skill_dependency_install_and_uninstall(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            workspace = root / "workspace"
            package_repo = root / "package-repo"
            skill_repo = root / "skill-repo"
            workspace.mkdir()
            self._write_skill_repo(skill_repo, "locked")
            skill_commit = self._git_commit(skill_repo)
            self._write_package(
                package_repo,
                manifest_extra=[
                    "skills:",
                    "  dependencies:",
                    "    - id: locked",
                    f"      source: git:{skill_repo}",
                    f"      ref: {skill_commit}",
                ],
                frontmatter_extra=[
                    "skills:",
                    "  only:",
                    "    - locked",
                ],
            )
            package_commit = self._git_commit(package_repo, tag="v2.0.0")
            subprocess.run(["git", "branch", "feature/x"], cwd=package_repo, check=True)

            with working_directory(workspace):
                entry, warnings = TeamPackageInstaller().install(f"git:{package_repo}@v2.0.0")
                self.assertEqual(TeamPackageInstaller().update("acme/software-team")[0].name, "acme/software-team")
                branch_entry, branch_warnings = TeamPackageInstaller().install(f"git:{package_repo}@feature/x")
                removed = TeamPackageInstaller().uninstall("acme/software-team")
                with self.assertRaisesRegex(TeamPackageError, "not installed"):
                    TeamPackageInstaller().uninstall("acme/software-team")
                with self.assertRaisesRegex(TeamPackageError, "not installed"):
                    TeamPackageInstaller().update("acme/software-team")

        self.assertEqual(entry.requested, "v2.0.0")
        self.assertEqual(entry.raw["resolved"], package_commit)
        self.assertEqual(entry.skill_dependencies[0].raw["requested"], skill_commit)
        self.assertTrue(any("does not match" in warning for warning in warnings))
        self.assertEqual(branch_entry.requested, "feature/x")
        self.assertEqual(branch_entry.raw["resolved"], package_commit)
        self.assertFalse(any("does not match" in warning for warning in branch_warnings))
        self.assertEqual(removed.name, "acme/software-team")
        self.assertFalse((workspace / ".coding-agents" / "skills" / "locked").exists())

    def test_install_stages_skill_dependencies_before_mutating_workspace(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            workspace = root / "workspace"
            empty_repo = root / "empty-skill-repo"
            workspace.mkdir()
            empty_repo.mkdir()
            (empty_repo / "README.md").write_text("no skill here", encoding="utf-8")
            self._git_commit(empty_repo)
            package = root / "pkg"
            self._write_package(
                package,
                manifest_extra=[
                    "skills:",
                    "  dependencies:",
                    "    - id: locked",
                    f"      source: git:{empty_repo}",
                ],
                frontmatter_extra=[
                    "skills:",
                    "  only:",
                    "    - locked",
                ],
            )

            with working_directory(workspace):
                with self.assertRaisesRegex(TeamPackageError, "does not contain SKILL.md"):
                    TeamPackageInstaller().install(str(package))

            self.assertFalse((workspace / ".coding-agents" / "packages").exists())
            self.assertFalse((workspace / ".coding-agents" / "skills").exists())

    def test_install_rejects_conflicting_skill_revisions_and_shares_identical_ones(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            workspace = root / "workspace"
            skill_repo = root / "skill-repo"
            workspace.mkdir()
            self._write_skill_repo(skill_repo, "locked")
            first_commit = self._git_commit(skill_repo)
            (skill_repo / "SKILL.md").write_text("locked skill v2", encoding="utf-8")
            second_commit = self._git_commit(skill_repo)
            skill_dependency = ["skills:", "  dependencies:", "    - id: locked", f"      source: git:{skill_repo}"]
            gated_frontmatter = ["skills:", "  only:", "    - locked"]
            package_a = root / "pkg-a"
            package_b = root / "pkg-b"
            package_b_aligned = root / "pkg-b-aligned"
            self._write_package(
                package_a,
                package_name="acme/team-a",
                manifest_extra=[*skill_dependency, f"      ref: {first_commit}"],
                frontmatter_extra=gated_frontmatter,
            )
            self._write_package(
                package_b,
                package_name="acme/team-b",
                manifest_extra=[*skill_dependency, f"      ref: {second_commit}"],
                frontmatter_extra=gated_frontmatter,
            )
            self._write_package(
                package_b_aligned,
                package_name="acme/team-b",
                manifest_extra=[*skill_dependency, f"      ref: {first_commit}"],
                frontmatter_extra=gated_frontmatter,
            )
            skill_file = workspace / ".coding-agents" / "skills" / "locked" / "SKILL.md"

            with working_directory(workspace):
                TeamPackageInstaller().install(str(package_a))
                with self.assertRaisesRegex(TeamPackageError, "already locked by package 'acme/team-a'"):
                    TeamPackageInstaller().install(str(package_b))
                self.assertEqual(
                    [package.name for package in TeamLockfileStore(workspace).packages()],
                    ["acme/team-a"],
                )
                self.assertEqual(skill_file.read_text(encoding="utf-8"), "locked skill")

                TeamPackageInstaller().install(str(package_b_aligned))
                TeamPackageInstaller().uninstall("acme/team-a")
                self.assertTrue(skill_file.is_file())
                TeamPackageInstaller().uninstall("acme/team-b")
                self.assertFalse(skill_file.exists())

    def test_installer_and_git_error_edges(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp)
            installer = TeamPackageInstaller(workspace)
            self.assertEqual(installer._split_git_source("git:git@github.com:org/repo.git"), ("git@github.com:org/repo.git", None))
            self.assertEqual(installer._split_git_source("git:git@github.com:org/repo.git@v1.2.3"), ("git@github.com:org/repo.git", "v1.2.3"))
            self.assertEqual(installer._split_git_source("git:https://example.test/repo.git@main"), ("https://example.test/repo.git", "main"))
            self.assertEqual(
                installer._split_git_source("git:https://example.test/repo.git@feature/x"),
                ("https://example.test/repo.git", "feature/x"),
            )
            self.assertEqual(installer._split_git_source("git:https://example.test"), ("https://example.test", None))
            self.assertEqual(installer._validated_repo_url("https://example.test/repo.git"), "https://example.test/repo.git")
            self.assertEqual(installer._validated_repo_url("ssh://git@example.test/repo.git"), "ssh://git@example.test/repo.git")
            self.assertEqual(installer._validated_repo_url("git@github.com:org/repo.git"), "git@github.com:org/repo.git")
            for repo_url in ("", "-upload-pack=evil", "ext::sh -c id", "http://example.test/repo.git", "relative/path"):
                with self.assertRaisesRegex(TeamPackageError, "Unsupported git source"):
                    installer._validated_repo_url(repo_url)
            for ref in ("--force", "v1 v2"):
                with self.assertRaisesRegex(TeamPackageError, "Unsupported git ref"):
                    installer._validated_git_ref(ref)
            with self.assertRaisesRegex(TeamPackageError, "escapes the packages directory"):
                installer._installed_package_path("..")
            with self.assertRaisesRegex(TeamPackageError, "escapes the skills directory"):
                installer._installed_skill_path("../../escape")
            with self.assertRaisesRegex(TeamPackageError, "does not exist"):
                installer.install(str(workspace / "missing"))
            with self.assertRaisesRegex(TeamPackageError, "git command"):
                installer._git(["definitely-not-a-git-command"])
            with self.assertRaisesRegex(TeamPackageError, "must use a git"):
                installer._stage_skill_dependency({"id": "skill", "source": "local"}, workspace / "stage")
            with self.assertRaisesRegex(TeamPackageError, "does not contain SKILL.md"):
                installer._skill_source_dir(workspace, "missing")
            self.assertIsNone(installer._warn_on_git_version_mismatch(PackageManifest(workspace, {"version": "1.0.0"}), None, []))
            matching_warnings: list[str] = []
            installer._warn_on_git_version_mismatch(PackageManifest(workspace, {"version": "1.0.0"}), "v1.0.0", matching_warnings)
            installer._warn_on_git_version_mismatch(PackageManifest(workspace, {"version": "1.0.0"}), "main", matching_warnings)
            self.assertEqual(matching_warnings, [])
            self.assertEqual(installer._local_source_label("relative-package", workspace), "relative-package")
            self.assertEqual(
                installer._local_source_label(str(Path.home() / "home-package"), Path.home() / "home-package"),
                "~/home-package",
            )
            installer._remove_unused_skill_dependencies(LockedPackage(raw={"dependencies": "bad"}))
            installer._remove_unused_skill_dependencies(LockedPackage(raw={"dependencies": {"skills": "bad"}}))
            installer._remove_unused_skill_dependencies(LockedPackage(raw={"dependencies": {"skills": ["bad"]}}))
            retained_skill = workspace / ".coding-agents" / "skills" / "retained"
            retained_skill.mkdir(parents=True)
            outside_dir = workspace / "outside-skill"
            outside_dir.mkdir()
            TeamLockfileStore(workspace).write(
                {
                    "packages": [
                        {"name": "bad-deps", "dependencies": "bad"},
                        {"name": "bad-skills", "dependencies": {"skills": "bad"}},
                        {"name": "mixed-entries", "dependencies": {"skills": ["bad-item"]}},
                        {
                            "name": "retainer",
                            "dependencies": {
                                "skills": [
                                    {"id": "retained", "installed_path": ".coding-agents/skills/retained"}
                                ]
                            },
                        },
                    ]
                }
            )
            installer._remove_unused_skill_dependencies(
                LockedPackage(
                    raw={
                        "dependencies": {
                            "skills": [
                                {"id": "retained", "installed_path": ".coding-agents/skills/retained"},
                                {"id": "outside", "installed_path": "outside-skill"},
                                {"id": "ghost", "installed_path": ".coding-agents/skills/ghost"},
                            ]
                        }
                    }
                )
            )
            self.assertTrue(retained_skill.exists())
            self.assertTrue(outside_dir.exists())

            TeamLockfileStore(workspace).upsert_package({"name": "escaping", "installed_path": "../outside"})
            with self.assertRaisesRegex(TeamPackageError, "escapes the packages directory"):
                installer.uninstall("escaping")
            self.assertTrue(
                any(package.name == "escaping" for package in TeamLockfileStore(workspace).packages())
            )

    def test_validator_reports_invalid_manifest_and_export_shapes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            workspace = root / "workspace"
            package = root / "invalid"
            workspace.mkdir()
            package.mkdir()
            (package / "coding-agents-package.yaml").write_text(
                "\n".join(
                    [
                        "schema_version: 2",
                        "name: Bad_Name",
                        "version: nope",
                        "compatibility:",
                        "  coding_agents: 'not-a-spec'",
                        "exports:",
                        "  teams:",
                        "    - id:",
                        "      path: teams/empty/team.yaml",
                        "    - id: missing-path",
                        "      path:",
                        "    - id: absolute",
                        "      path: /tmp/team.yaml",
                        "    - id: outside",
                        "      path: ../team.yaml",
                        "    - id: broken",
                        "      path: teams/broken/team.yaml",
                        "    - id: mismatch",
                        "      path: teams/mismatch/team.yaml",
                        "skills:",
                        "  dependencies:",
                        "    - id:",
                        "      source: local",
                        "      ref: 1",
                        "    - id: ../../evil",
                        "      source: git:https://example.test/skills.git",
                        "  external:",
                        "    - id:",
                        "      install_hint: 1",
                        "requires:",
                        "  env:",
                        "    - 1INVALID",
                    ]
                )
                + "\n",
                encoding="utf-8",
            )
            self._write_team_only(package / "teams" / "mismatch", "other")

            with working_directory(workspace), self.assertRaises(TeamPackageError) as raised:
                TeamPackageValidator().validate(package)

            no_exports = root / "no-exports"
            no_exports.mkdir()
            (no_exports / "coding-agents-package.yaml").write_text(
                "schema_version: 1\nname: acme/no-exports\nversion: 1.0.0\ncompatibility:\n  coding_agents: '>999'\n",
                encoding="utf-8",
            )
            with working_directory(workspace), self.assertRaisesRegex(TeamPackageError, "exports.teams"):
                TeamPackageValidator().validate(no_exports)

            missing_skill = root / "missing-skill"
            self._write_package(
                missing_skill,
                frontmatter_extra=[
                    "skills:",
                    "  only:",
                    "    - undeclared",
                ],
            )
            with working_directory(workspace), self.assertRaisesRegex(TeamPackageError, "not bundled"):
                TeamPackageValidator().validate(missing_skill)

        message = str(raised.exception)
        self.assertIn("schema_version", message)
        self.assertIn("Package name", message)
        self.assertIn("Package version", message)
        self.assertIn("compatibility.coding_agents", message)
        self.assertIn("exports.teams[1].id", message)
        self.assertIn("exports.teams[2].path", message)
        self.assertIn("Package paths must be relative", message)
        self.assertIn("must stay within", message)
        self.assertIn("does not exist", message)
        self.assertIn("does not match", message)
        self.assertIn("skills.dependencies[1].id", message)
        self.assertIn("skills.dependencies[2].id", message)
        self.assertIn("skills.external[1].id", message)
        self.assertIn("requires.env", message)

    def test_manifest_loader_manifest_properties_and_lockfile_fallbacks(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            package = root / "package"
            package.mkdir()
            with self.assertRaisesRegex(TeamPackageError, "does not exist"):
                PackageManifestLoader().load(package)
            (package / "coding-agents-package.yaml").write_text("not yaml", encoding="utf-8")
            with self.assertRaisesRegex(TeamPackageError, "Expected YAML"):
                PackageManifestLoader().load(package)
            (package / "coding-agents-package.yaml").write_text("- item\n", encoding="utf-8")
            with self.assertRaisesRegex(TeamPackageError, "YAML mapping"):
                PackageManifestLoader().load(package)
            manifest = PackageManifest(
                package,
                {
                    "description": "Desc",
                    "compatibility": "bad",
                    "exports": "bad",
                    "skills": "bad",
                    "requires": "bad",
                },
            )
            self.assertEqual(manifest.description, "Desc")
            self.assertIsNone(manifest.coding_agents_specifier)
            self.assertEqual(manifest.team_exports, [])
            self.assertEqual(manifest.skill_dependencies, [])
            self.assertEqual(manifest.external_skills, [])
            self.assertEqual(manifest.required_env, ())
            manifest = PackageManifest(package, {"exports": {"teams": "bad"}, "skills": {"dependencies": "bad", "external": "bad"}, "requires": {"env": "bad"}})
            self.assertEqual(manifest.team_exports, [])
            self.assertEqual(manifest.skill_dependencies, [])
            self.assertEqual(manifest.external_skills, [])
            self.assertEqual(manifest.required_env, ())

            store = TeamLockfileStore(root)
            self.assertEqual(store.read()["packages"], [])
            store.path.parent.mkdir(parents=True)
            store.path.write_text("{", encoding="utf-8")
            with self.assertRaisesRegex(TeamPackageError, "unreadable"):
                store.read()
            store.path.write_text("[]", encoding="utf-8")
            with self.assertRaisesRegex(TeamPackageError, "unreadable"):
                store.packages()
            store.path.write_text('{"packages": "bad"}', encoding="utf-8")
            self.assertEqual(store.packages(), [])
            self.assertIsNone(store.remove_package("missing"))
            self.assertEqual(store.absolute_path("/tmp/example"), Path("/tmp/example"))
            self.assertTrue(store.relative_path(Path("/tmp/example")).startswith("/"))
            self.assertIsNone(store.contained_path(".coding-agents/packages", store.packages_root))
            self.assertIsNone(store.contained_path("/tmp/outside", store.packages_root))
            self.assertIsNone(store.contained_path("../outside", store.packages_root))
            self.assertEqual(
                store.contained_path(".coding-agents/packages/acme/pkg", store.packages_root),
                (store.packages_root / "acme" / "pkg").resolve(),
            )

    def test_trust_store_version_hasher_locator_and_risk_edges(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            codex_home = root / "codex-home"
            with patch.dict(os.environ, {"CODEX_HOME": str(codex_home)}):
                store = TeamPackageTrustStore()
                store.path.parent.mkdir(parents=True)
                store.path.write_text('{"trusted_packages": "bad"}', encoding="utf-8")
                self.assertFalse(store.is_trusted("pkg", "sha256-one"))
                store.path.write_text("{", encoding="utf-8")
                self.assertEqual(store._read()["trusted_packages"], [])
                store.path.write_text("[]", encoding="utf-8")
                self.assertEqual(store._read()["trusted_packages"], [])
                store.trust("pkg", "sha256-one")
                store.trust("pkg", "sha256-one")
                self.assertEqual(
                    store.status(LockedPackage(raw={"name": "pkg", "integrity": "sha256-one", "risk_flags": ["shell"]})),
                    "trusted",
                )
                self.assertEqual(
                    store.status(LockedPackage(raw={"name": "pkg", "integrity": "sha256-two", "risk_flags": ["shell"]})),
                    "untrusted",
                )
                self.assertEqual(store.status(LockedPackage(raw={"risk_flags": []})), "not_required")
                self.assertEqual(store.status(LockedPackage(raw={"risk_flags": "bad"})), "not_required")
            with patch.dict(os.environ, {"CODEX_HOME": ""}):
                self.assertEqual(TeamPackageTrustStore().path, Path.home() / ".codex" / "coding-agents" / "trust.json")

            package_path = root / ".coding-agents" / "packages" / "acme" / "pkg" / "team.yaml"
            package_path.parent.mkdir(parents=True)
            package_path.write_text("", encoding="utf-8")
            self.assertIsNone(InstalledPackageLocator(root).package_for_team_file(root / "outside.yaml"))
            self.assertFalse(InstalledPackageLocator(root).is_installed_package_path(root / "outside.yaml"))
            TeamLockfileStore(root).upsert_package({"name": "escaper", "installed_path": "../outside", "dependencies": {}})
            TeamLockfileStore(root).upsert_package({"name": "pkg", "installed_path": ".coding-agents/packages/acme/pkg", "dependencies": "bad"})
            self.assertEqual(InstalledPackageLocator(root).locked_skill_ids(package_path), ())
            TeamLockfileStore(root).upsert_package({"name": "pkg", "installed_path": ".coding-agents/packages/acme/pkg", "dependencies": {"skills": "bad"}})
            self.assertEqual(InstalledPackageLocator(root).locked_skill_ids(package_path), ())
            TeamLockfileStore(root).path.write_text("{", encoding="utf-8")
            self.assertIsNone(InstalledPackageLocator(root).package_for_team_file(package_path))

            hash_root = root / "hash"
            (hash_root / ".git").mkdir(parents=True)
            (hash_root / ".git" / "config").write_text("skip", encoding="utf-8")
            (hash_root / "__pycache__").mkdir()
            (hash_root / "__pycache__" / "x.pyc").write_text("skip", encoding="utf-8")
            (hash_root / ".DS_Store").write_text("skip", encoding="utf-8")
            (hash_root / "included.txt").write_text("include", encoding="utf-8")
            self.assertTrue(ContentHasher().hash_directory(hash_root).startswith("sha256-"))

            risky_team = team(
                custom_tools={"tool": object()},
                mcp_servers={
                    "stdio": SimpleNamespace(transport="stdio"),
                    "remote": SimpleNamespace(transport="sse"),
                },
                agents={"entry": agent("entry", entrypoint=True, toolsets=("shell",))},
                team_defaults=defaults(execution_backend_env="EXECUTION_BACKEND", execution_backend_default="none"),
            )
            self.assertEqual(
                PackageRiskScanner().risk_flags(risky_team),
                ("custom_tools", "stdio_mcp", "remote_mcp", "shell"),
            )
            self.assertEqual(PackageRiskScanner().risk_flags(team()), ())
            inert_shell_team = team(agents={"entry": agent("entry", entrypoint=True, toolsets=("shell",))})
            self.assertEqual(PackageRiskScanner().risk_flags(inert_shell_team), ())
            execute_team = team(
                agents={"entry": agent("entry", entrypoint=True, toolsets=("custom", "missing"))},
                toolsets={"custom": SimpleNamespace(name="custom", tools=(SimpleNamespace(name="execute"),))},
            )
            self.assertEqual(PackageRiskScanner().risk_flags(execute_team), ("shell",))
            renamed_team = team(
                agents={"entry": agent("entry", entrypoint=True, toolsets=("custom",))},
                toolsets={"custom": SimpleNamespace(name="custom", tools=(SimpleNamespace(name="read_file"),))},
            )
            self.assertEqual(PackageRiskScanner().risk_flags(renamed_team), ())

            with patch.object(version_module.metadata, "version", side_effect=version_module.metadata.PackageNotFoundError):
                self.assertEqual(version_module.current_coding_agents_version(), "0.1.0")
                with patch.object(version_module.Path, "read_text", side_effect=OSError):
                    self.assertEqual(version_module.current_coding_agents_version(), "0.0.0")
                with patch.object(version_module.tomllib, "loads", return_value={"project": {}}):
                    self.assertEqual(version_module.current_coding_agents_version(), "0.0.0")

    def test_discovery_missing_package_and_invalid_lock_entries(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            workspace = root / "workspace"
            repository = root / "repo"
            workspace.mkdir()
            TeamLockfileStore(workspace).write(
                {
                    "packages": [
                        {"name": "bad-teams", "installed_path": ".coding-agents/packages/bad", "teams": "bad"},
                        {"name": "bad-team-entry", "installed_path": ".coding-agents/packages/bad", "teams": ["bad"]},
                        {"name": "escaping-install", "installed_path": "../outside", "teams": [{"id": "escape", "path": "team.yaml"}]},
                        {
                            "name": "escaping-team-path",
                            "installed_path": ".coding-agents/packages/escaping-team-path",
                            "teams": [{"id": "escape", "path": "../../../../escape/team.yaml"}, {"id": "empty", "path": ""}],
                        },
                        {
                            "name": "missing",
                            "version": "1.0.0",
                            "source": "pkg",
                            "integrity": "sha256-one",
                            "installed_path": ".coding-agents/packages/missing",
                            "teams": [{"id": "missing", "path": "team.yaml"}],
                            "risk_flags": ["shell"],
                            "requires": "bad",
                        },
                        {
                            "name": "missing-env-shape",
                            "version": "1.0.0",
                            "source": "pkg",
                            "integrity": "sha256-two",
                            "installed_path": ".coding-agents/packages/missing-env-shape",
                            "teams": [{"id": "missing-env-shape", "path": "team.yaml"}],
                            "risk_flags": [],
                            "requires": {"env": "bad"},
                        },
                    ]
                }
            )
            service = TeamDiscoveryService(repository_root=repository, workspace_dir=workspace)
            with patch.dict(os.environ, {"CODEX_HOME": str(root / "codex-home")}):
                candidates = service._package_candidate_files()
                missing = service._descriptor(candidates[0][0], candidates[0][1], package=candidates[0][2])
                no_id = service._missing_package_descriptor(candidates[0][0], {})
                discovery = service.discover()
                (workspace / ".coding-agents" / "team-lock.json").write_text("{", encoding="utf-8")
                tolerant = service.discover()

        self.assertEqual(len(candidates), 2)
        self.assertEqual(missing["lock_status"], "missing")
        self.assertEqual(missing["trust_status"], "untrusted")
        self.assertEqual(missing["missing_required_env"], [])
        self.assertIsNone(no_id)
        self.assertEqual([item["team_id"] for item in discovery["teams"]], ["missing", "missing-env-shape"])
        self.assertFalse(discovery["teams"][0]["conversation_available"])
        self.assertEqual(discovery["teams"][0]["lock_status"], "missing")
        self.assertEqual(tolerant["teams"], [])

    def _write_package(
        self,
        root: Path,
        *,
        package_name: str | None = "acme/software-team",
        team_id: str = "software",
        manifest_extra: list[str] | None = None,
        team_extra: list[str] | None = None,
        frontmatter_extra: list[str] | None = None,
    ) -> None:
        team_dir = root / "teams" / "software"
        agents_dir = team_dir / "agents"
        agents_dir.mkdir(parents=True)
        manifest_lines = [
            "schema_version: 1",
            *( [f"name: {package_name}"] if package_name is not None else [] ),
            "version: 1.0.0",
            "compatibility:",
            "  coding_agents: '>=0.1.0'",
            "exports:",
            "  teams:",
            f"    - id: {team_id}",
            "      path: teams/software/team.yaml",
            *(manifest_extra or []),
        ]
        (root / "coding-agents-package.yaml").write_text("\n".join(manifest_lines) + "\n", encoding="utf-8")
        team_lines = [
            "schema_version: 1",
            f"id: {team_id}",
            "working_directory: .",
            *(team_extra or []),
            "agents:",
            "  entry:",
            "    kind: deepagent",
            "    config: agents/entry.mdc",
            "    entrypoint: true",
            "conversation:",
        ]
        (team_dir / "team.yaml").write_text("\n".join(team_lines) + "\n", encoding="utf-8")
        frontmatter_lines = [
            "---",
            "description: Entry",
            *(frontmatter_extra or []),
            "---",
            "Prompt",
        ]
        (agents_dir / "entry.mdc").write_text("\n".join(frontmatter_lines) + "\n", encoding="utf-8")

    def _write_skill_repo(self, root: Path, skill_id: str) -> None:
        root.mkdir(parents=True)
        (root / "SKILL.md").write_text(f"{skill_id} skill", encoding="utf-8")

    def _write_team_only(self, root: Path, team_id: str) -> None:
        agents_dir = root / "agents"
        agents_dir.mkdir(parents=True)
        (root / "team.yaml").write_text(
            "\n".join(
                [
                    "schema_version: 1",
                    f"id: {team_id}",
                    "working_directory: .",
                    "agents:",
                    "  entry:",
                    "    kind: deepagent",
                    "    config: agents/entry.mdc",
                    "    entrypoint: true",
                ]
            )
            + "\n",
            encoding="utf-8",
        )
        (agents_dir / "entry.mdc").write_text("---\ndescription: Entry\n---\nPrompt\n", encoding="utf-8")

    def _git_commit(self, root: Path, *, tag: str | None = None) -> str:
        subprocess.run(["git", "init", "--quiet"], cwd=root, check=True)
        subprocess.run(["git", "add", "."], cwd=root, check=True)
        subprocess.run(
            [
                "git",
                "-c",
                "user.email=test@example.com",
                "-c",
                "user.name=Test User",
                "commit",
                "--quiet",
                "-m",
                "initial",
            ],
            cwd=root,
            check=True,
        )
        if tag:
            subprocess.run(["git", "tag", tag], cwd=root, check=True)
        return subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=root, text=True).strip()

    def _write_discovery_team(self, path: Path, team_id: str) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            "\n".join(
                [
                    "schema_version: 1",
                    f"id: {team_id}",
                    "conversation:",
                    "agents:",
                    "  guide:",
                    "    kind: deepagent",
                    "    conversation:",
                    "      aliases:",
                    "        - mentor",
                ]
            )
            + "\n",
            encoding="utf-8",
        )


@contextmanager
def working_directory(path: Path):
    previous = Path.cwd()
    os.chdir(path)
    try:
        yield
    finally:
        os.chdir(previous)


if __name__ == "__main__":
    unittest.main()
