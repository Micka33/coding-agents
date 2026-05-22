"""Scout subagent for fast codebase reconnaissance."""

from __future__ import annotations

import fnmatch
import os
import shlex
import subprocess
from pathlib import Path
from typing import Any, Sequence

from langchain.agents import create_agent
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.runnables import Runnable
from langchain_core.tools import BaseTool, StructuredTool


SCOUT_PROMPT = """You are a scout. Quickly investigate a codebase and return structured findings that another agent can use without re-reading everything.

Your output will be passed to an agent who has NOT seen the files you explored.

Thoroughness (infer from task, default medium):
- Quick: Targeted lookups, key files only
- Medium: Follow imports, read critical sections
- Thorough: Trace all dependencies, check tests/types

Strategy:
1. grep/find to locate relevant code
2. Read key sections (not entire files)
3. Identify types, interfaces, key functions
4. Note dependencies between files

Tool guidance:
- Prefer glob, grep, ls, and read_file over execute.
- execute is read-only reconnaissance only. Do not use shell operators,
  pipelines, redirection, or destructive commands.
- If execute returns an error, switch to glob/grep/read_file instead of
  retrying the same command.

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
_MAX_EXECUTE_OUTPUT = 20_000
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
_ALLOWED_EXECUTABLES = {
    "awk",
    "cat",
    "find",
    "git",
    "head",
    "ls",
    "pwd",
    "rg",
    "sed",
    "tail",
    "wc",
}
_ALLOWED_GIT_SUBCOMMANDS = {
    "branch",
    "diff",
    "grep",
    "log",
    "ls-files",
    "rev-parse",
    "show",
    "status",
}
_SHELL_OPERATORS = {"|", ">", ">>", "<", "<<", ";", "&&", "||"}


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
                if _is_excluded(child, root) or _is_sensitive(child):
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
            if _is_sensitive(target):
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
                if _is_excluded(candidate, root) or _is_sensitive(candidate):
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
        """Search project files for a text or regex pattern."""

        try:
            target = _resolve_path(root, path)
            if not target.exists():
                return [_tool_error(f"Path not found: {path}")]

            rg_command = [
                "rg",
                "--line-number",
                "--no-heading",
                "--color",
                "never",
                "--glob",
                "!.env*",
                "--glob",
                "!*.pem",
                "--glob",
                "!*.key",
                pattern,
                str(target.relative_to(root)),
            ]
            if file_glob:
                rg_command[7:7] = ["--glob", file_glob]

            result = _run_command(root, rg_command, timeout=20)
            if result["exit_code"] in {0, 1} and result["stdout"]:
                return _parse_rg_output(root, result["stdout"], max_matches=max_matches)

            return _python_grep(root, target, pattern, file_glob, max_matches)
        except Exception as exc:  # pragma: no cover - defensive tool boundary
            return [_tool_error(str(exc))]

    def execute(command: str, timeout: int = 30) -> dict[str, Any]:
        """Run a read-only reconnaissance shell command in the project root."""

        try:
            args = shlex.split(command)
            if not args:
                return _tool_error("command must not be empty")
            _validate_read_only_command(args)
            return _run_command(root, args, timeout=max(1, min(timeout, 30)))
        except Exception as exc:  # pragma: no cover - defensive tool boundary
            return _tool_error(str(exc), command=command)

    return [
        StructuredTool.from_function(ls, name="ls"),
        StructuredTool.from_function(read_file, name="read_file"),
        StructuredTool.from_function(glob, name="glob"),
        StructuredTool.from_function(grep, name="grep"),
        StructuredTool.from_function(execute, name="execute"),
    ]


def _resolve_path(root: Path, path: str) -> Path:
    if not path:
        path = "."
    raw = Path(path)
    if raw.is_absolute():
        resolved = raw.resolve()
        try:
            resolved.relative_to(root)
        except ValueError:
            resolved = (root / path.lstrip("/")).resolve()
    else:
        resolved = (root / path.lstrip("/")).resolve()
    try:
        resolved.relative_to(root)
    except ValueError as exc:
        raise PermissionError(f"Path is outside project root: {path}") from exc
    return resolved


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
    try:
        resolved = path.resolve()
        resolved.relative_to(root)
    except (OSError, ValueError):
        return True
    return False


def _is_sensitive(path: Path) -> bool:
    return path.name.startswith(".env") or path.suffix in _SENSITIVE_SUFFIXES


def _run_command(root: Path, args: list[str], *, timeout: int) -> dict[str, Any]:
    env = {
        "HOME": os.environ.get("HOME", ""),
        "PATH": os.environ.get("PATH", ""),
    }
    try:
        completed = subprocess.run(
            args,
            cwd=root,
            env=env,
            text=True,
            capture_output=True,
            timeout=timeout,
            check=False,
        )
    except FileNotFoundError as exc:
        raise RuntimeError(f"Command not found: {args[0]}") from exc
    return {
        "command": shlex.join(args),
        "exit_code": completed.returncode,
        "stdout": _truncate(completed.stdout, _MAX_EXECUTE_OUTPUT),
        "stderr": _truncate(completed.stderr, _MAX_EXECUTE_OUTPUT),
    }


def _validate_read_only_command(args: list[str]) -> None:
    if any(token in _SHELL_OPERATORS for token in args):
        raise PermissionError("Shell operators and redirection are not allowed in scout execute.")

    executable = Path(args[0]).name
    if executable not in _ALLOWED_EXECUTABLES:
        raise PermissionError(f"Scout execute does not allow command: {executable}")

    if executable == "git":
        subcommand = _first_non_option(args[1:])
        if subcommand not in _ALLOWED_GIT_SUBCOMMANDS:
            raise PermissionError(f"Scout execute does not allow git subcommand: {subcommand}")

    if executable == "sed" and any(arg == "-i" or arg.startswith("-i") for arg in args[1:]):
        raise PermissionError("Scout execute does not allow in-place sed edits.")

    for arg in args[1:]:
        if arg.startswith("/") or ".." in Path(arg).parts:
            raise PermissionError("Scout execute arguments must stay inside the project root.")


def _first_non_option(args: list[str]) -> str | None:
    for arg in args:
        if not arg.startswith("-"):
            return arg
    return None


def _parse_rg_output(root: Path, output: str, *, max_matches: int) -> list[dict[str, Any]]:
    matches: list[dict[str, Any]] = []
    for line in output.splitlines():
        if len(matches) >= max_matches:
            break
        path, line_number, text = _split_rg_line(line)
        if path is None or line_number is None:
            continue
        target = _resolve_path(root, path)
        if _is_excluded(target, root) or _is_sensitive(target):
            continue
        matches.append({"path": path, "line": line_number, "text": text})
    return matches


def _split_rg_line(line: str) -> tuple[str | None, int | None, str]:
    parts = line.split(":", 2)
    if len(parts) != 3:
        return None, None, line
    path, line_number, text = parts
    try:
        return path, int(line_number), text
    except ValueError:
        return None, None, line


def _python_grep(
    root: Path,
    target: Path,
    pattern: str,
    file_glob: str | None,
    max_matches: int,
) -> list[dict[str, Any]]:
    matches: list[dict[str, Any]] = []
    candidates = [target] if target.is_file() else target.rglob("*")
    for candidate in candidates:
        if len(matches) >= max_matches:
            break
        if not candidate.is_file() or _is_excluded(candidate, root) or _is_sensitive(candidate):
            continue
        relative = _relative_path(root, candidate)
        if file_glob and not fnmatch.fnmatch(relative, file_glob):
            continue
        for line_number, line in enumerate(candidate.read_text(encoding="utf-8", errors="replace").splitlines(), start=1):
            if pattern in line:
                matches.append({"path": relative, "line": line_number, "text": line})
                if len(matches) >= max_matches:
                    break
    return matches


def _truncate(value: str, limit: int) -> str:
    if len(value) <= limit:
        return value
    return value[:limit].rstrip() + "\n...[truncated]"


def _tool_error(message: str, **extra: Any) -> dict[str, Any]:
    return {"error": message, **extra}
