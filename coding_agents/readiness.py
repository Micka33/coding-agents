"""Machine-readable readiness gate parsing and enforcement."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from coding_agents.config import DEFAULT_ARTIFACTS_DIR
from coding_agents.paths import validate_artifacts_dir

READINESS_GATE_FILENAME = "readiness-gate.yaml"
FULL_IMPLEMENTATION_SCOPE = "full_implementation"
READINESS_GATE_KEYS = (
    "approved",
    "approval_scope",
    "approved_by",
    "approved_date",
    "notes",
)

DEFAULT_READINESS_GATE_YAML = """# Machine-readable readiness gate for implementation mode.
# This file fails closed until a human explicitly approves full implementation.
approved: false
approval_scope: none
approved_by: ""
approved_date: ""
notes: ""
"""


class ReadinessGateError(RuntimeError):
    """Raised when implementation mode is blocked by readiness state."""


@dataclass(frozen=True)
class ReadinessGateStatus:
    """Parsed readiness gate state."""

    path: Path
    approved: bool
    approval_scope: str
    approved_by: str
    approved_date: str
    notes: str


def readiness_gate_path(
    root_dir: str | Path = ".",
    artifacts_dir: str | Path = DEFAULT_ARTIFACTS_DIR,
) -> Path:
    """Return the expected readiness gate artifact path."""

    root = Path(root_dir).resolve()
    safe_artifacts_dir = validate_artifacts_dir(artifacts_dir, root)
    return root / safe_artifacts_dir / READINESS_GATE_FILENAME


def read_readiness_gate(
    root_dir: str | Path = ".",
    artifacts_dir: str | Path = DEFAULT_ARTIFACTS_DIR,
) -> ReadinessGateStatus:
    """Read and parse the machine-readable readiness gate.

    The parser intentionally supports only the small scalar YAML subset used by
    the gate artifact. Unsupported or malformed content is treated as invalid so
    implementation mode fails closed.
    """

    try:
        path = readiness_gate_path(root_dir, artifacts_dir)
    except ValueError as exc:
        raise ReadinessGateError(
            f"Implementation mode denied: readiness gate path is unsafe: {exc}"
        ) from exc
    if not _gate_filename_exists_exactly(path):
        raise ReadinessGateError(
            f"Implementation mode denied: readiness gate file is missing at {path}."
        )
    if path.is_symlink():
        raise ReadinessGateError(
            f"Implementation mode denied: readiness gate file must not be a symlink at {path}."
        )
    if not path.exists():
        raise ReadinessGateError(
            f"Implementation mode denied: readiness gate file is missing at {path}."
        )

    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise ReadinessGateError(
            f"Implementation mode denied: readiness gate file could not be read at {path}: {exc}"
        ) from exc

    values = _parse_readiness_yaml(text, path=path)
    return _status_from_values(values, path=path)


def assert_readiness_approved(
    root_dir: str | Path = ".",
    artifacts_dir: str | Path = DEFAULT_ARTIFACTS_DIR,
) -> ReadinessGateStatus:
    """Raise unless the readiness gate approves full implementation mode."""

    status = read_readiness_gate(root_dir, artifacts_dir)
    problems: list[str] = []
    if not status.approved:
        problems.append("approved must be true")
    if status.approval_scope != FULL_IMPLEMENTATION_SCOPE:
        problems.append(f"approval_scope must be {FULL_IMPLEMENTATION_SCOPE!r}")
    if not status.approved_by.strip():
        problems.append("approved_by must be non-empty")
    if not status.approved_date.strip():
        problems.append("approved_date must be non-empty")

    if problems:
        raise ReadinessGateError(
            "Implementation mode denied: readiness gate is not approved for full implementation "
            f"at {status.path} ({'; '.join(problems)})."
        )

    return status


def _parse_readiness_yaml(text: str, *, path: Path) -> dict[str, Any]:
    values: dict[str, Any] = {}
    for line_number, raw_line in enumerate(text.splitlines(), start=1):
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if ":" not in line:
            raise ReadinessGateError(
                f"Invalid readiness gate at {path}: line {line_number} is not a 'key: value' scalar."
            )

        key, raw_value = line.split(":", 1)
        key = key.strip()
        if not key:
            raise ReadinessGateError(
                f"Invalid readiness gate at {path}: line {line_number} has an empty key."
            )
        if key in values:
            raise ReadinessGateError(
                f"Invalid readiness gate at {path}: duplicate key {key!r} on line {line_number}."
            )

        values[key] = _parse_scalar(raw_value.strip(), path=path, line_number=line_number)

    return values


def _gate_filename_exists_exactly(path: Path) -> bool:
    try:
        return any(child.name == path.name for child in path.parent.iterdir())
    except FileNotFoundError:
        return False
    except OSError:
        return path.exists()


def _parse_scalar(value: str, *, path: Path, line_number: int) -> str | bool:
    if value == "":
        return ""

    lowered = value.lower()
    if lowered == "true":
        return True
    if lowered == "false":
        return False

    if value[0] in {"'", '"'} or value[-1] in {"'", '"'}:
        if len(value) < 2 or value[0] != value[-1]:
            raise ReadinessGateError(
                f"Invalid readiness gate at {path}: line {line_number} has mismatched quotes."
            )
        return value[1:-1]

    return value


def _status_from_values(values: dict[str, Any], *, path: Path) -> ReadinessGateStatus:
    unknown = sorted(set(values) - set(READINESS_GATE_KEYS))
    if unknown:
        raise ReadinessGateError(
            f"Invalid readiness gate at {path}: unsupported keys: {', '.join(unknown)}."
        )

    missing = [key for key in READINESS_GATE_KEYS if key not in values]
    if missing:
        raise ReadinessGateError(
            f"Invalid readiness gate at {path}: missing required keys: {', '.join(missing)}."
        )

    approved = values["approved"]
    if not isinstance(approved, bool):
        raise ReadinessGateError(
            f"Invalid readiness gate at {path}: approved must be true or false."
        )

    string_values: dict[str, str] = {}
    for key in ("approval_scope", "approved_by", "approved_date", "notes"):
        value = values[key]
        if not isinstance(value, str):
            raise ReadinessGateError(
                f"Invalid readiness gate at {path}: {key} must be a string scalar."
            )
        string_values[key] = value

    return ReadinessGateStatus(
        path=path,
        approved=approved,
        approval_scope=string_values["approval_scope"],
        approved_by=string_values["approved_by"],
        approved_date=string_values["approved_date"],
        notes=string_values["notes"],
    )
