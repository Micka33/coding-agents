from __future__ import annotations

import mimetypes
import os
import subprocess
from pathlib import Path
from typing import Any

from src.webapp_studio.backend.api.studio_api_error import StudioApiError
from src.webapp_studio.backend.api.studio_attachment_ref_factory import MAX_ATTACHMENT_BYTES

_MAX_WORKSPACE_FILE_RESULTS = 50
_MAX_WORKSPACE_SCAN_FILES = 5000
_WORKSPACE_EXCLUDED_DIRS = {
    ".coding-agents",
    ".git",
    ".hg",
    ".mypy_cache",
    ".next",
    ".pytest_cache",
    ".ruff_cache",
    ".svn",
    ".tox",
    ".venv",
    "__pycache__",
    "build",
    "coverage",
    "dist",
    "node_modules",
}


class StudioWorkspaceFileBrowser:
    def __init__(self, root_dir: Path) -> None:
        self._root_dir = root_dir.resolve()

    def files(self, *, query: str = "", limit: int = 20) -> dict[str, Any]:
        safe_limit = max(1, min(limit, _MAX_WORKSPACE_FILE_RESULTS))
        normalized_query = query.strip().lstrip("@").casefold()
        matches = []
        for relative_path in self._workspace_file_candidates():
            item = self._workspace_file_item(relative_path)
            if item is None:
                continue
            score = self._workspace_file_score(item, normalized_query)
            if score is None:
                continue
            matches.append((score, str(item["path"]).casefold(), item))
            if len(matches) >= safe_limit * 4:
                break
        matches.sort(key=lambda match: (match[0], match[1]))
        return {"files": [item for _score, _path, item in matches[:safe_limit]]}

    def file_path(self, relative_path: str, *, field: str) -> Path:
        if not relative_path:
            raise StudioApiError(status_code=400, code="invalid_request", message="workspace path is required.", field=field)
        raw_path = Path(relative_path)
        if raw_path.is_absolute():
            raise StudioApiError(status_code=400, code="invalid_request", message="workspace path must be relative.", field=field)
        path = (self._root_dir / raw_path).resolve()
        if not self._path_is_within_root(path):
            raise StudioApiError(status_code=400, code="invalid_request", message="workspace path is outside the root.", field=field)
        if not path.exists():
            raise StudioApiError(status_code=404, code="not_found", message="workspace file not found.", field=field)
        if not path.is_file():
            raise StudioApiError(status_code=400, code="invalid_request", message="workspace path must be a file.", field=field)
        try:
            size_bytes = path.stat().st_size
        except OSError as error:
            raise StudioApiError(status_code=404, code="not_found", message="workspace file not found.", field=field) from error
        if size_bytes > MAX_ATTACHMENT_BYTES:
            raise StudioApiError(status_code=400, code="invalid_request", message="workspace file exceeds the 10 MiB limit.", field=field)
        return path

    def _workspace_file_candidates(self) -> list[str]:
        git_paths = self._git_workspace_file_candidates()
        if git_paths is not None:
            return git_paths
        return self._scanned_workspace_file_candidates()

    def _git_workspace_file_candidates(self) -> list[str] | None:
        try:
            result = subprocess.run(
                ["git", "-C", str(self._root_dir), "ls-files", "-co", "--exclude-standard", "-z"],
                check=True,
                capture_output=True,
            )
        except (OSError, subprocess.CalledProcessError):
            return None
        paths = []
        for raw_path in result.stdout.split(b"\0"):
            if not raw_path:
                continue
            try:
                path = raw_path.decode("utf-8")
            except UnicodeDecodeError:
                continue
            if self._workspace_path_has_excluded_part(path):
                continue
            paths.append(path)
        return paths

    def _scanned_workspace_file_candidates(self) -> list[str]:
        paths = []
        scanned = 0
        for current_root, dirnames, filenames in os.walk(self._root_dir):
            dirnames[:] = [dirname for dirname in dirnames if dirname not in _WORKSPACE_EXCLUDED_DIRS]
            for filename in filenames:
                if scanned >= _MAX_WORKSPACE_SCAN_FILES:
                    return paths
                path = Path(current_root) / filename
                relative_path = path.relative_to(self._root_dir).as_posix()
                if self._workspace_path_has_excluded_part(relative_path):
                    continue
                scanned += 1
                paths.append(relative_path)
        return paths

    def _workspace_file_item(self, relative_path: str) -> dict[str, Any] | None:
        try:
            path = self.file_path(relative_path, field="path")
        except StudioApiError:
            return None
        try:
            size_bytes = path.stat().st_size
        except OSError:
            return None
        return {
            "path": path.relative_to(self._root_dir).as_posix(),
            "filename": path.name,
            "media_type": mimetypes.guess_type(path.name)[0],
            "size_bytes": size_bytes,
        }

    def _workspace_file_score(self, item: dict[str, Any], query: str) -> int | None:
        if not query:
            return 0
        path = str(item["path"]).casefold()
        filename = str(item["filename"]).casefold()
        if filename.startswith(query):
            return 0
        if path.startswith(query):
            return 1
        if query in filename:
            return 2
        if query in path:
            return 3
        return None

    def _workspace_path_has_excluded_part(self, path: str) -> bool:
        return any(part in _WORKSPACE_EXCLUDED_DIRS for part in Path(path).parts)

    def _path_is_within_root(self, path: Path) -> bool:
        try:
            path.relative_to(self._root_dir)
        except ValueError:
            return False
        return True
