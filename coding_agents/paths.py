"""Repository path validation helpers for governance controls."""

from __future__ import annotations

from collections.abc import Iterable
from pathlib import Path, PureWindowsPath

_GLOB_METACHARS = frozenset("*?[]{}!")
_REPO_WIDE_WRITE_VALUES = {
    "",
    ".",
    "./",
    "/",
    "/.",
    "/./",
    "**",
    "**/",
    "**/*",
    "/**",
    "/**/",
    "/**/*",
    "*",
    "*/",
    "/*",
}


class PathValidationError(ValueError):
    """Raised when a configured repository path is unsafe or too broad."""


def validate_artifacts_dir(
    artifacts_dir: str | Path,
    root_dir: str | Path | None = None,
) -> str:
    """Return a safe repository-relative artifact directory.

    Artifact directories are allowed to move away from the default only when the
    value remains a literal, contained, repository-relative directory. Values
    that could relocate the readiness gate outside expected repository scope or
    widen artifact writes fail closed before any files are created. When a root
    is provided, existing path components must not be symlinks and the resolved
    target must remain under the resolved repository root.
    """

    raw = _path_text(artifacts_dir, "artifacts_dir")
    normalized = _normalize_separators(raw)
    if normalized in {".", "./", "/", "/.", "/./"}:
        raise PathValidationError("artifacts_dir must be a repository-relative subdirectory, not '.' or '/'")
    if normalized.startswith("/") or _has_windows_anchor(raw):
        raise PathValidationError("artifacts_dir must be repository-relative; absolute paths are not allowed")
    _reject_glob_metacharacters(normalized, "artifacts_dir")

    relative = _strip_trailing_slash(_strip_leading_current_dirs(normalized))
    parts = _literal_parts(relative, "artifacts_dir")
    if root_dir is not None:
        _validate_repo_relative_location(
            root_dir,
            parts,
            "artifacts_dir",
            must_be_directory=True,
        )
    return "/".join(parts)


def normalize_implementation_write_paths(
    paths: Iterable[str | Path],
    *,
    root_dir: str | Path | None = ".",
) -> list[str]:
    """Return DeepAgents permission paths for literal implementation write scopes.

    Each input is interpreted as either an exact repository path or, when it ends
    in '/', a literal directory whose descendants are included. Glob syntax and
    repo-wide/root-equivalent values are rejected. Root validation defaults to
    the current working directory; existing components must not be symlinks and
    resolved targets/parents must remain under the repository root.
    """

    normalized: list[str] = []
    for path in paths:
        normalized.extend(normalize_implementation_write_path(path, root_dir=root_dir))
    return normalized


def normalize_implementation_write_path(
    path: str | Path,
    *,
    root_dir: str | Path | None = ".",
) -> list[str]:
    """Return one exact permission path, or a directory plus descendants."""

    raw = _path_text(path, "implementation write paths")
    normalized = _normalize_separators(raw)
    normalized = _strip_leading_current_dirs(normalized)
    if normalized in _REPO_WIDE_WRITE_VALUES:
        raise PathValidationError(
            "implementation write paths must be task-scoped; repo-wide writes are not allowed"
        )
    if normalized.startswith("/") or _has_windows_anchor(raw):
        raise PathValidationError(
            "implementation write paths must be repository-relative paths, not host absolute paths"
        )
    _reject_glob_metacharacters(normalized, "implementation write paths")

    is_directory = normalized.endswith("/")
    relative = _strip_trailing_slash(normalized).strip("/")
    parts = _literal_parts(relative, "implementation write paths")
    if root_dir is not None:
        _validate_repo_relative_location(
            root_dir,
            parts,
            "implementation write paths",
            require_existing_directory=is_directory,
        )
    virtual_path = "/" + "/".join(parts)
    if is_directory:
        return [virtual_path, f"{virtual_path}/**"]
    return [virtual_path]


def _validate_repo_relative_location(
    root_dir: str | Path,
    parts: tuple[str, ...],
    field_name: str,
    *,
    require_existing_directory: bool = False,
    must_be_directory: bool = False,
) -> None:
    root = Path(root_dir).resolve()
    if not root.exists() or not root.is_dir():
        raise PathValidationError(f"{field_name} root must be an existing repository directory")

    target = root.joinpath(*parts)
    _reject_existing_symlink_components(root, parts, field_name)
    _assert_resolved_under_root(target, root, field_name)

    if require_existing_directory and (not target.exists() or not target.is_dir()):
        raise PathValidationError(
            f"{field_name} directory scopes must refer to an existing non-symlink directory"
        )
    if must_be_directory and target.exists() and not target.is_dir():
        raise PathValidationError(f"{field_name} must refer to a directory path")


def _reject_existing_symlink_components(root: Path, parts: tuple[str, ...], field_name: str) -> None:
    current = root
    for index, part in enumerate(parts):
        current = current / part
        if current.is_symlink():
            raise PathValidationError(f"{field_name} must not traverse symlink components: {current}")
        if not current.exists():
            break
        if index < len(parts) - 1 and not current.is_dir():
            raise PathValidationError(f"{field_name} parent components must be directories: {current}")


def _assert_resolved_under_root(target: Path, root: Path, field_name: str) -> None:
    try:
        target.resolve(strict=False).relative_to(root)
    except (OSError, RuntimeError, ValueError) as exc:
        raise PathValidationError(
            f"{field_name} must resolve within the repository root"
        ) from exc


def _path_text(path: str | Path, field_name: str) -> str:
    value = str(path).strip()
    if not value:
        raise PathValidationError(f"{field_name} must not be empty")
    return value


def _normalize_separators(path: str) -> str:
    return path.replace("\\", "/")


def _strip_leading_current_dirs(path: str) -> str:
    stripped = path
    while stripped.startswith("./"):
        stripped = stripped[2:]
    return stripped


def _strip_trailing_slash(path: str) -> str:
    if path == "/":
        return path
    return path.rstrip("/")


def _literal_parts(path: str, field_name: str) -> tuple[str, ...]:
    if not path or path in {".", "/"}:
        raise PathValidationError(f"{field_name} must be a repository-relative path below the repository root")

    parts = tuple(path.split("/"))
    if any(part in {"", ".", "..", "~"} for part in parts):
        raise PathValidationError(f"{field_name} must not contain '.', '..', '~', or empty path segments")
    return parts


def _reject_glob_metacharacters(path: str, field_name: str) -> None:
    bad = sorted(set(path) & _GLOB_METACHARS)
    if bad:
        characters = "".join(bad)
        raise PathValidationError(
            f"{field_name} must be literal paths; glob/metacharacters are not allowed: {characters}"
        )


def _has_windows_anchor(path: str) -> bool:
    windows_path = PureWindowsPath(path)
    return bool(windows_path.drive or windows_path.root.startswith("\\"))
