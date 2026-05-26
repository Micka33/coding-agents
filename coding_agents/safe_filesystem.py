"""Symlink-safe filesystem backend for local development agents."""

from __future__ import annotations

import os
import subprocess
import uuid
from datetime import datetime
from pathlib import Path
from typing import Iterator

import wcmatch.glob as wcglob
from deepagents.backends import FilesystemBackend
from deepagents.backends.protocol import (
    ExecuteResponse,
    FileInfo,
    GlobResult,
    GrepMatch,
    GrepResult,
    LsResult,
    SandboxBackendProtocol,
)

from coding_agents.redaction import redact_secrets

_WCMATCH_FLAGS = wcglob.BRACE | wcglob.GLOBSTAR
_SENSITIVE_SUFFIXES = {".key", ".pem", ".p12", ".pfx"}
_SENSITIVE_FILENAMES = {
    ".netrc",
    ".npmrc",
    ".pypirc",
    "application_default_credentials.json",
    "credentials.json",
    "id_rsa",
    "id_ed25519",
    "secrets.json",
}


class SafeFilesystemBackend(FilesystemBackend):
    """Filesystem backend that rejects unsafe aliases before file operations.

    DeepAgents permissions are evaluated against the requested virtual path, while
    the raw backend resolves symlinks before accessing the host filesystem. This
    subclass keeps virtual-path semantics but rejects existing symlink path
    components, final symlinks, and sensitive filename targets before reads,
    writes, edits, lists, globs, and greps can use an alias to bypass a
    sensitive/out-of-scope target.
    """

    def __init__(
        self,
        root_dir: str | Path | None = None,
        virtual_mode: bool | None = True,
        max_file_size_mb: int = 10,
    ) -> None:
        super().__init__(
            root_dir=root_dir,
            virtual_mode=virtual_mode,
            max_file_size_mb=max_file_size_mb,
        )

    def _resolve_path(self, key: str) -> Path:
        """Resolve a path after rejecting symlink components in the request."""

        try:
            if self.virtual_mode:
                relative = _virtual_relative_path(key)
                _reject_sensitive_path(relative)
                self._reject_symlink_components(relative)
                resolved = (self.cwd / relative).resolve(strict=False)
                try:
                    resolved_relative = resolved.relative_to(self.cwd)
                except ValueError as exc:
                    raise PermissionError(f"Path outside root directory: {key}") from exc
                _reject_sensitive_path(resolved_relative)
                return resolved

            path = Path(key)
            unresolved = path if path.is_absolute() else self.cwd / path
            self._reject_symlink_alias(unresolved)
            resolved = unresolved.resolve(strict=False)
            try:
                _reject_sensitive_path(resolved.relative_to(self.cwd))
            except ValueError:
                pass
            return resolved
        except ValueError as exc:
            raise PermissionError(str(exc)) from exc

    def ls(self, path: str) -> LsResult:
        """List direct children, skipping symlink aliases."""

        try:
            dir_path = self._resolve_path(path)
            if not dir_path.exists() or not dir_path.is_dir():
                return LsResult(entries=[])
        except (OSError, RuntimeError, ValueError) as exc:
            return LsResult(error=f"Cannot list '{path}': {exc}", entries=[])

        entries: list[FileInfo] = []
        errors: list[str] = []
        try:
            children = sorted(dir_path.iterdir(), key=lambda child: child.name)
        except (OSError, RuntimeError) as exc:
            return LsResult(error=f"Listing of '{path}' aborted: {exc}", entries=[])

        for child in children:
            try:
                if self._has_symlink_alias(child) or self._is_sensitive_alias(child):
                    continue
                is_dir = child.is_dir()
                is_file = child.is_file()
            except (OSError, RuntimeError) as exc:
                errors.append(f"child error: cannot stat '{child}': {exc}")
                continue
            if not is_dir and not is_file:
                continue

            entry: FileInfo = {
                "path": self._display_path(child) + ("/" if is_dir else ""),
                "is_dir": is_dir,
            }
            try:
                stat = child.stat()
                entry["size"] = 0 if is_dir else int(stat.st_size)
                entry["modified_at"] = datetime.fromtimestamp(stat.st_mtime).isoformat()
            except OSError:
                pass
            entries.append(entry)

        error = "\n".join(sorted(errors)) if errors else None
        return LsResult(error=error, entries=entries)

    def glob(self, pattern: str, path: str = "/") -> GlobResult:
        """Find matching regular files without traversing or returning symlinks."""

        clean_pattern = pattern.lstrip("/") if pattern.startswith("/") else pattern
        if self.virtual_mode and ".." in Path(clean_pattern).parts:
            return GlobResult(error="Path traversal not allowed in glob pattern", matches=[])

        try:
            search_path = self.cwd if path == "/" else self._resolve_path(path)
            if not search_path.exists() or not search_path.is_dir():
                return GlobResult(matches=[])
        except (OSError, RuntimeError, ValueError) as exc:
            return GlobResult(error=f"Error globbing path '{path}': {exc}", matches=[])

        results: list[FileInfo] = []
        try:
            matched_paths = search_path.rglob(clean_pattern)
            for matched_path in matched_paths:
                try:
                    if (
                        self._has_symlink_alias(matched_path)
                        or self._is_sensitive_alias(matched_path)
                        or not matched_path.is_file()
                    ):
                        continue
                    entry: FileInfo = {"path": self._display_path(matched_path), "is_dir": False}
                    try:
                        stat = matched_path.stat()
                        entry["size"] = int(stat.st_size)
                        entry["modified_at"] = datetime.fromtimestamp(stat.st_mtime).isoformat()
                    except OSError:
                        pass
                    results.append(entry)
                except (OSError, RuntimeError):
                    continue
        except (OSError, RuntimeError, ValueError) as exc:
            results.sort(key=lambda item: item.get("path", ""))
            return GlobResult(error=f"Glob of '{path}' aborted partway: {exc}", matches=results)

        results.sort(key=lambda item: item.get("path", ""))
        return GlobResult(matches=results)

    def grep(self, pattern: str, path: str | None = None, glob: str | None = None) -> GrepResult:
        """Search regular files with Python literal matching and no symlink traversal."""

        search_path = path or "."
        try:
            base_path = self._resolve_path(search_path)
            if not base_path.exists():
                return GrepResult(matches=[])
        except (OSError, RuntimeError, ValueError) as exc:
            return GrepResult(error=f"Error searching path '{search_path}': {exc}", matches=[])

        matches: list[GrepMatch] = []
        for file_path in self._grep_candidates(base_path):
            rel_for_glob = _relative_for_glob(base_path, file_path)
            if glob and not wcglob.globmatch(rel_for_glob, glob, flags=_WCMATCH_FLAGS):
                continue
            try:
                if file_path.stat().st_size > self.max_file_size_bytes:
                    continue
                lines = file_path.read_text(encoding="utf-8", errors="replace").splitlines()
            except (OSError, RuntimeError, UnicodeDecodeError):
                continue
            for line_number, line in enumerate(lines, start=1):
                if pattern in line:
                    matches.append(
                        {
                            "path": self._display_path(file_path),
                            "line": line_number,
                            "text": line,
                        }
                    )
        return GrepResult(matches=matches)

    def _grep_candidates(self, base_path: Path) -> Iterator[Path]:
        if self._has_symlink_alias(base_path) or self._is_sensitive_alias(base_path):
            return
        if base_path.is_file():
            yield base_path
            return
        if not base_path.is_dir():
            return

        for dirpath, dirnames, filenames in os.walk(base_path, followlinks=False):
            current_dir = Path(dirpath)
            safe_dirnames: list[str] = []
            for dirname in dirnames:
                child_dir = current_dir / dirname
                if not self._has_symlink_alias(child_dir) and not self._is_sensitive_alias(child_dir):
                    safe_dirnames.append(dirname)
            dirnames[:] = safe_dirnames

            for filename in filenames:
                candidate = current_dir / filename
                try:
                    if (
                        self._has_symlink_alias(candidate)
                        or self._is_sensitive_alias(candidate)
                        or not candidate.is_file()
                    ):
                        continue
                except (OSError, RuntimeError):
                    continue
                yield candidate

    def _display_path(self, path: Path) -> str:
        if not self.virtual_mode:
            return str(path)
        return "/" + path.relative_to(self.cwd).as_posix()

    def _reject_symlink_components(self, relative: Path) -> None:
        current = self.cwd
        for part in relative.parts:
            if part in {"", "."}:
                continue
            current = current / part
            if current.is_symlink():
                raise PermissionError(f"Refusing to access symlink path: {current.relative_to(self.cwd).as_posix()}")
            if not current.exists():
                break

    def _reject_symlink_alias(self, path: Path) -> None:
        if self._has_symlink_alias(path):
            raise PermissionError(f"Refusing to access symlink path: {path}")

    def _is_sensitive_alias(self, path: Path) -> bool:
        try:
            relative = path.relative_to(self.cwd) if path.is_absolute() else path
        except ValueError:
            return True
        return _is_sensitive_path(relative)

    def _has_symlink_alias(self, path: Path) -> bool:
        try:
            relative = path.relative_to(self.cwd) if path.is_absolute() else path
        except ValueError:
            return True

        current = self.cwd if path.is_absolute() else Path()
        for part in relative.parts:
            if part in {"", "."}:
                continue
            current = current / part
            try:
                if current.is_symlink():
                    return True
                if not current.exists():
                    break
            except OSError:
                return True
        return False


class SafeLocalShellBackend(SafeFilesystemBackend, SandboxBackendProtocol):
    """Safe filesystem backend plus explicit host shell execution.

    Filesystem tools keep the symlink and sensitive-path protections from
    `SafeFilesystemBackend`. The `execute` tool is intentionally a trusted local
    escape hatch: commands run through the host shell with the current user's
    permissions and are not constrained by filesystem permissions.
    """

    def __init__(
        self,
        root_dir: str | Path | None = None,
        virtual_mode: bool | None = True,
        max_file_size_mb: int = 10,
        *,
        timeout: int = 120,
        max_output_bytes: int = 100_000,
        env: dict[str, str] | None = None,
        inherit_env: bool = True,
    ) -> None:
        if timeout <= 0:
            raise ValueError(f"timeout must be positive, got {timeout}")
        if max_output_bytes <= 0:
            raise ValueError(f"max_output_bytes must be positive, got {max_output_bytes}")

        super().__init__(
            root_dir=root_dir,
            virtual_mode=virtual_mode,
            max_file_size_mb=max_file_size_mb,
        )
        self._default_timeout = timeout
        self._max_output_bytes = max_output_bytes
        self._env = os.environ.copy() if inherit_env else {}
        if env is not None:
            self._env.update(env)
        self._sandbox_id = f"local-{uuid.uuid4().hex[:8]}"

    @property
    def id(self) -> str:
        """Return the local execution backend identifier."""

        return self._sandbox_id

    def execute(self, command: str, *, timeout: int | None = None) -> ExecuteResponse:
        """Execute a shell command directly on the host machine."""

        if not command or not isinstance(command, str):
            return ExecuteResponse(
                output="Error: Command must be a non-empty string.",
                exit_code=1,
                truncated=False,
            )

        effective_timeout = timeout if timeout is not None else self._default_timeout
        if effective_timeout <= 0:
            raise ValueError(f"timeout must be positive, got {effective_timeout}")

        try:
            completed = subprocess.run(
                command,
                check=False,
                shell=True,
                capture_output=True,
                stdin=subprocess.DEVNULL,
                text=True,
                timeout=effective_timeout,
                env=self._env,
                cwd=str(self.cwd),
            )
        except subprocess.TimeoutExpired:
            return ExecuteResponse(
                output=f"Error: Command timed out after {effective_timeout} seconds.",
                exit_code=124,
                truncated=False,
            )
        except Exception as exc:  # pragma: no cover - defensive command boundary
            return ExecuteResponse(
                output=f"Error executing command ({type(exc).__name__}): {redact_secrets(exc, env=self._env)}",
                exit_code=1,
                truncated=False,
            )

        output_parts: list[str] = []
        if completed.stdout:
            output_parts.append(completed.stdout)
        if completed.stderr:
            output_parts.extend(
                f"[stderr] {line}"
                for line in completed.stderr.rstrip().splitlines()
            )
        output = "\n".join(output_parts) if output_parts else "<no output>"
        output = redact_secrets(output, env=self._env)

        truncated = False
        if len(output) > self._max_output_bytes:
            output = output[: self._max_output_bytes].rstrip()
            output += f"\n\n... Output truncated at {self._max_output_bytes} bytes."
            truncated = True

        if completed.returncode != 0:
            output = f"{output.rstrip()}\n\nExit code: {completed.returncode}"

        return ExecuteResponse(
            output=output,
            exit_code=completed.returncode,
            truncated=truncated,
        )


def _virtual_relative_path(key: str) -> Path:
    raw = key if key else "."
    vpath = raw if raw.startswith("/") else "/" + raw
    relative = Path(vpath.lstrip("/"))
    if not relative.parts:
        return Path(".")
    if any(part in {"..", "~"} for part in relative.parts):
        raise ValueError("Path traversal not allowed")
    return relative


def _is_sensitive_path(path: Path) -> bool:
    for part in path.parts:
        name = part.casefold()
        suffix = Path(part).suffix.casefold()
        if name.startswith(".env") or name in _SENSITIVE_FILENAMES or suffix in _SENSITIVE_SUFFIXES:
            return True
    return False


def _reject_sensitive_path(path: Path) -> None:
    if _is_sensitive_path(path):
        raise PermissionError(f"Refusing to access sensitive path: {path.as_posix() or '.'}")


def _relative_for_glob(base_path: Path, file_path: Path) -> str:
    root = base_path if base_path.is_dir() else base_path.parent
    try:
        return file_path.relative_to(root).as_posix()
    except ValueError:
        return file_path.name
