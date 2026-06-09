from __future__ import annotations

from pathlib import PurePosixPath

from deepagents.backends.protocol import LsResult


class SkillFilteringBackend:
    def __init__(self, backend: object, allowed_skill_ids: tuple[str, ...]) -> None:
        self._backend = backend
        self._allowed_skill_ids = frozenset(allowed_skill_ids)

    def __getattr__(self, name: str) -> object:
        return getattr(self._backend, name)

    def ls(self, path: str) -> LsResult:
        result = self._backend.ls(path)
        if not isinstance(result, LsResult) or result.error or not self._is_root(path):
            return result
        return LsResult(entries=self._filtered_entries(result.entries or []))

    async def als(self, path: str) -> LsResult:
        result = await self._backend.als(path)
        if not isinstance(result, LsResult) or result.error or not self._is_root(path):
            return result
        return LsResult(entries=self._filtered_entries(result.entries or []))

    def _filtered_entries(self, entries: list[dict]) -> list[dict]:
        return [
            entry
            for entry in entries
            if entry.get("is_dir") and self._root_name(str(entry.get("path", ""))) in self._allowed_skill_ids
        ]

    def _root_name(self, path: str) -> str:
        return PurePosixPath(path).as_posix().strip("/").split("/", 1)[0]

    def _is_root(self, path: str) -> bool:
        return PurePosixPath(path).as_posix().rstrip("/") in {"", "."}
