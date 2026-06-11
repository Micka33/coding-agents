from __future__ import annotations

import argparse
import sys

from src.team_loader.errors.team_loader_error import TeamLoaderError

from src.team_packages.installer import TeamPackageInstaller
from src.team_packages.lockfile_store import TeamLockfileStore
from src.team_packages.package_error import TeamPackageError
from src.team_packages.package_validator import TeamPackageValidator
from src.team_packages.trust_store import TeamPackageTrustStore


class TeamPackageCli:
    def main(self, argv: list[str] | None = None) -> int:
        parser = argparse.ArgumentParser(description="Manage coding-agents team packages.")
        subparsers = parser.add_subparsers(dest="command", required=True)
        validate = subparsers.add_parser("validate", help="Validate a local team package.")
        validate.add_argument("package")
        install = subparsers.add_parser("install", help="Install a local or git team package.")
        install.add_argument("source")
        subparsers.add_parser("list", help="List installed team packages.")
        update = subparsers.add_parser("update", help="Update installed team packages.")
        update.add_argument("package", nargs="?")
        uninstall = subparsers.add_parser("uninstall", help="Uninstall a team package.")
        uninstall.add_argument("package")
        trust = subparsers.add_parser("trust", help="Trust the currently locked integrity for a package.")
        trust.add_argument("package")
        args = parser.parse_args(argv)
        try:
            return self._dispatch(args)
        except (TeamPackageError, TeamLoaderError, OSError) as error:
            print(str(error), file=sys.stderr)
            return 1

    def _dispatch(self, args: argparse.Namespace) -> int:
        if args.command == "validate":
            manifest, warnings, _teams = TeamPackageValidator().validate(args.package)
            self._print_warnings(warnings)
            print(f"Package valid: {manifest.name}@{manifest.version}")
            return 0
        if args.command == "install":
            entry, warnings = TeamPackageInstaller().install(args.source)
            self._print_warnings(warnings)
            print(f"Installed {entry.name}@{entry.version}")
            return 0
        if args.command == "list":
            self._list()
            return 0
        if args.command == "update":
            updated = TeamPackageInstaller().update(args.package)
            for entry in updated:
                print(f"Updated {entry.name}@{entry.version}")
            if not updated:
                print("No packages installed.")
            return 0
        if args.command == "uninstall":
            removed = TeamPackageInstaller().uninstall(args.package)
            print(f"Uninstalled {removed.name}")
            return 0
        if args.command == "trust":
            self._trust(args.package)
            return 0
        raise TeamPackageError(f"Unsupported team command: {args.command}")

    def _list(self) -> None:
        trust_store = TeamPackageTrustStore()
        packages = TeamLockfileStore().packages()
        if not packages:
            print("No packages installed.")
            return
        for package in packages:
            flags = ", ".join(package.risk_flags) if package.risk_flags else "none"
            trust = trust_store.status(package)
            print(f"{package.name}@{package.version} trust={trust} risk={flags}")
            for team in package.teams:
                print(f"  team {team.id} -> {team.path}")

    def _trust(self, package_name: str) -> None:
        package = next(
            (item for item in TeamLockfileStore().packages() if item.name == package_name),
            None,
        )
        if package is None:
            raise TeamPackageError(f"Package is not installed: {package_name}")
        TeamPackageTrustStore().trust(package.name, package.integrity)
        print(f"Trusted {package.name} at {package.integrity}")

    def _print_warnings(self, warnings: list[str]) -> None:
        for warning in warnings:
            print(f"warning: {warning}", file=sys.stderr)
