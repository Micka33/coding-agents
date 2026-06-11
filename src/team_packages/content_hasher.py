from __future__ import annotations

import hashlib
from pathlib import Path


class ContentHasher:
    def hash_directory(self, root: Path) -> str:
        digest = hashlib.sha256()
        for path in self._files(root):
            relative = path.relative_to(root).as_posix()
            digest.update(relative.encode("utf-8"))
            digest.update(b"\0")
            digest.update(path.read_bytes())
            digest.update(b"\0")
        return f"sha256-{digest.hexdigest()}"

    def _files(self, root: Path) -> list[Path]:
        skipped_dirs = {".git", "__pycache__"}
        skipped_files = {".DS_Store"}
        files: list[Path] = []
        for path in root.rglob("*"):
            relative_parts = set(path.relative_to(root).parts)
            if relative_parts & skipped_dirs:
                continue
            if path.name in skipped_files:
                continue
            if path.is_file():
                files.append(path)
        return sorted(files, key=lambda item: item.relative_to(root).as_posix())
