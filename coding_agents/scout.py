"""Scout subagent for fast codebase reconnaissance."""

from __future__ import annotations

import fnmatch
from pathlib import Path
from typing import Any, Sequence

from langchain.agents import create_agent
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.tools import BaseTool, StructuredTool


SCOUT_PROMPT = """You are a scout. Quickly investigate a codebase and return structured findings that another agent can use without re-reading everything.

Your output will be passed to an agent who has NOT seen the files you explored.

Thoroughness (infer from task, default medium):
- Quick: Targeted lookups, key files only
- Medium: Follow imports, read critical sections
- Thorough: Trace all dependencies, check tests/types

Strategy:
1. glob/grep to locate relevant code
2. Read key sections (not entire files)
3. Identify types, interfaces, key functions
4. Note dependencies between files

Tool guidance:
- Use glob, grep, ls, and read_file for local repository reconnaissance.
- Use web_search and fetch_url when external context is needed.
- Do not attempt to run shell commands; scout has no command execution tool.

Output format:

## Files Retrieved
List with exact line ranges:
1. `path/to/file.ts` (lines 10-50) - Description of what's here
2. `path/to/other.ts` (lines 100-150) - Description
3. ...

## Key Code
Critical types, interfaces, or functions:

```typescript
interface Example {
  // actual code from the files
}
```

```typescript
function keyFunction() {
  // actual implementation
}
```

## Architecture
Brief explanation of how the pieces connect.

## Start Here
Which file to look at first and why.
"""

_MAX_READ_CHARS = 20_000
_EXCLUDED_PARTS = {
    ".coding-agents",
    ".git",
    ".mypy_cache",
    ".pytest_cache",
    ".ruff_cache",
    ".venv",
    "__pycache__",
    "node_modules",
}
_SENSITIVE_SUFFIXES = {".key", ".pem", ".p12", ".pfx"}
_SENSITIVE_FILENAMES = {"id_rsa", "id_ed25519"}


def create_scout_subagent(
    *,
    model: str | BaseChatModel,
    root_dir: Path,
    tools: Sequence[BaseTool],
) -> dict[str, Any]:
    """Create the compiled scout subagent spec."""

    runnable = create_agent(
        model=model,
        system_prompt=SCOUT_PROMPT,
        tools=[*scout_tools(root_dir), *tools],
        name="scout",
    )
    return {
        "name": "scout",
        "description": "Fast codebase recon that returns compressed context for handoff to other agents.",
        "runnable": runnable,
    }


def scout_tools(root_dir: Path) -> list[BaseTool]:
    """Return scoped tools for scout codebase reconnaissance."""

    root = root_dir.resolve()

    def ls(path: str = ".") -> list[dict[str, Any]]:
        """List files and directories under the project root."""

        try:
            target = _resolve_path(root, path)
            if not target.exists():
                return [_tool_error(f"Path not found: {path}")]
            if not target.is_dir():
                return [_tool_error(f"Path is not a directory: {path}")]

            items: list[dict[str, Any]] = []
            for child in sorted(target.iterdir(), key=lambda item: item.name):
                if _is_excluded(child, root) or _is_sensitive(child.relative_to(root)):
                    continue
                items.append(
                    {
                        "path": _relative_path(root, child),
                        "kind": "directory" if child.is_dir() else "file",
                    }
                )
            return items[:200]
        except Exception as exc:  # pragma: no cover - defensive tool boundary
            return [_tool_error(str(exc))]

    def read_file(path: str, start_line: int = 1, end_line: int | None = None) -> dict[str, Any]:
        """Read a bounded line range from a project file."""

        try:
            target = _resolve_path(root, path)
            if _is_sensitive(target.relative_to(root)):
                return _tool_error(f"Refusing to read sensitive file: {_relative_path(root, target)}")
            if not target.is_file():
                return _tool_error(f"Path is not a file: {path}")

            lines = target.read_text(encoding="utf-8", errors="replace").splitlines()
            first = max(1, start_line)
            last = len(lines) if end_line is None else max(first, end_line)
            selected = lines[first - 1 : last]
            content = "\n".join(f"{line_no}: {line}" for line_no, line in enumerate(selected, start=first))
            return {
                "path": _relative_path(root, target),
                "start_line": first,
                "end_line": min(last, len(lines)),
                "content": _truncate(content, _MAX_READ_CHARS),
            }
        except Exception as exc:  # pragma: no cover - defensive tool boundary
            return _tool_error(str(exc))

    def glob(pattern: str, max_results: int = 200) -> list[str]:
        """Find files matching a glob pattern under the project root."""

        try:
            clean_pattern = _clean_relative_pattern(pattern)
            matches: list[str] = []
            for candidate in root.glob(clean_pattern):
                if _is_excluded(candidate, root) or _is_sensitive(candidate.relative_to(root)):
                    continue
                matches.append(_relative_path(root, candidate))
                if len(matches) >= max(1, min(max_results, 500)):
                    break
            return sorted(matches)
        except Exception as exc:  # pragma: no cover - defensive tool boundary
            return [f"Error: {exc}"]

    def grep(
        pattern: str,
        path: str = ".",
        file_glob: str | None = None,
        max_matches: int = 50,
    ) -> list[dict[str, Any]]:
        """Search project files for a literal text pattern."""

        try:
            target = _resolve_path(root, path)
            if not target.exists():
                return [_tool_error(f"Path not found: {path}")]
            if _is_sensitive(target.relative_to(root)):
                return [_tool_error(f"Refusing to search sensitive path: {_relative_path(root, target)}")]

            return _python_grep(root, target, pattern, file_glob, max_matches)
        except Exception as exc:  # pragma: no cover - defensive tool boundary
            return [_tool_error(str(exc))]

    return [
        StructuredTool.from_function(ls, name="ls"),
        StructuredTool.from_function(read_file, name="read_file"),
        StructuredTool.from_function(glob, name="glob"),
        StructuredTool.from_function(grep, name="grep"),
    ]


def _resolve_path(root: Path, path: str) -> Path:
    if not path:
        path = "."

    relative = _relative_input_path(root, path)
    if _is_sensitive(relative):
        raise PermissionError(f"Refusing to access sensitive path: {relative.as_posix() or '.'}")

    target = root / relative
    _reject_symlink_components(root, relative)

    resolved = target.resolve(strict=False)
    try:
        resolved_relative = resolved.relative_to(root)
    except ValueError as exc:
        raise PermissionError(f"Path is outside project root: {path}") from exc
    if _is_sensitive(resolved_relative):
        raise PermissionError(f"Refusing to access sensitive path: {resolved_relative.as_posix() or '.'}")
    return resolved


def _relative_input_path(root: Path, path: str) -> Path:
    raw = Path(path)
    if raw.is_absolute():
        try:
            relative = raw.relative_to(root)
        except ValueError:
            relative = Path(path.lstrip("/"))
    else:
        relative = Path(path.lstrip("/"))

    if not relative.parts:
        return Path(".")
    if any(part in {"..", "~"} for part in relative.parts):
        raise PermissionError(f"Path traversal is not allowed: {path}")
    return relative


def _reject_symlink_components(root: Path, relative: Path) -> None:
    current = root
    for part in relative.parts:
        if part in {"", "."}:
            continue
        current = current / part
        try:
            is_symlink = current.is_symlink()
            exists = current.exists()
        except OSError as exc:
            raise PermissionError(f"Refusing to access unsafe path: {current}") from exc
        if is_symlink:
            raise PermissionError(f"Refusing to access symlink path: {current.relative_to(root).as_posix()}")
        if not exists:
            break


def _relative_path(root: Path, path: Path) -> str:
    return path.relative_to(root).as_posix()


def _clean_relative_pattern(pattern: str) -> str:
    clean = pattern.lstrip("/") or "**/*"
    if ".." in Path(clean).parts:
        raise PermissionError(f"Path traversal is not allowed in glob: {pattern}")
    return clean


def _is_excluded(path: Path, root: Path) -> bool:
    try:
        relative = path.relative_to(root)
    except ValueError:
        return True
    if any(part in _EXCLUDED_PARTS for part in relative.parts):
        return True
    if _has_symlink_component(path, root):
        return True
    try:
        resolved = path.resolve(strict=False)
        resolved.relative_to(root)
    except (OSError, ValueError):
        return True
    return False


def _has_symlink_component(path: Path, root: Path) -> bool:
    try:
        relative = path.relative_to(root)
    except ValueError:
        return True

    current = root
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


def _is_sensitive(path: Path) -> bool:
    for part in path.parts:
        name = part.casefold()
        suffix = Path(part).suffix.casefold()
        if name.startswith(".env") or name in _SENSITIVE_FILENAMES or suffix in _SENSITIVE_SUFFIXES:
            return True
    return False


def _python_grep(
    root: Path,
    target: Path,
    pattern: str,
    file_glob: str | None,
    max_matches: int,
) -> list[dict[str, Any]]:
    limit = max(0, min(max_matches, 500))
    if limit == 0:
        return []

    matches: list[dict[str, Any]] = []
    candidates = [target] if target.is_file() else target.rglob("*")
    for candidate in candidates:
        if len(matches) >= limit:
            break
        if _is_excluded(candidate, root) or not candidate.is_file():
            continue
        relative = _relative_path(root, candidate)
        if _is_sensitive(Path(relative)):
            continue
        if file_glob and not fnmatch.fnmatch(relative, file_glob):
            continue
        try:
            lines = candidate.read_text(encoding="utf-8", errors="replace").splitlines()
        except OSError:
            continue
        for line_number, line in enumerate(lines, start=1):
            if pattern in line:
                matches.append({"path": relative, "line": line_number, "text": line})
                if len(matches) >= limit:
                    break
    return matches


def _truncate(value: str, limit: int) -> str:
    if len(value) <= limit:
        return value
    return value[:limit].rstrip() + "\n...[truncated]"


def _tool_error(message: str, **extra: Any) -> dict[str, Any]:
    return {"error": message, **extra}
