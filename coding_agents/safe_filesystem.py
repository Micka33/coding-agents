"""Symlink-safe filesystem backend for local development agents."""

from __future__ import annotations

import os
from datetime import datetime
from pathlib import Path
from typing import Iterator

import wcmatch.glob as wcglob
from deepagents.backends import FilesystemBackend
from deepagents.backends.protocol import FileInfo, GlobResult, GrepMatch, GrepResult, LsResult

_WCMATCH_FLAGS = wcglob.BRACE | wcglob.GLOBSTAR
_SENSITIVE_SUFFIXES = {".key", ".pem", ".p12", ".pfx"}
_SENSITIVE_FILENAMES = {"id_rsa", "id_ed25519"}


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
