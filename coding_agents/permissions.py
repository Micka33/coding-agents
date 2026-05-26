"""Filesystem permissions for development-agent modes."""

from __future__ import annotations

from collections.abc import Iterable
from pathlib import Path

from deepagents.middleware.filesystem import FilesystemPermission

from coding_agents.config import AgentMode
from coding_agents.paths import normalize_implementation_write_paths, validate_artifacts_dir
from coding_agents.readiness import READINESS_GATE_FILENAME


def _case_insensitive_literal_pattern(value: str) -> str:
    parts: list[str] = []
    for char in value:
        folded = char.casefold()
        if len(char) == 1 and "a" <= folded <= "z":
            parts.append(f"[{folded}{folded.upper()}]")
        else:
            parts.append(char)
    return "".join(parts)


_SECRET_LIKE_FILENAMES = (
    ".netrc",
    ".npmrc",
    ".pypirc",
    "application_default_credentials.json",
    "credentials.json",
    "secrets.json",
)


SENSITIVE_READ_DENY_PATHS = [
    f"/{_case_insensitive_literal_pattern('.env')}",
    f"/{_case_insensitive_literal_pattern('.env')}/**",
    f"/{_case_insensitive_literal_pattern('.env')}.*",
    f"/{_case_insensitive_literal_pattern('.env')}.*/**",
    f"/**/{_case_insensitive_literal_pattern('.env')}",
    f"/**/{_case_insensitive_literal_pattern('.env')}/**",
    f"/**/{_case_insensitive_literal_pattern('.env')}.*",
    f"/**/{_case_insensitive_literal_pattern('.env')}.*/**",
    f"/*{_case_insensitive_literal_pattern('.pem')}",
    f"/*{_case_insensitive_literal_pattern('.key')}",
    f"/*{_case_insensitive_literal_pattern('.p12')}",
    f"/*{_case_insensitive_literal_pattern('.pfx')}",
    f"/**/*{_case_insensitive_literal_pattern('.pem')}",
    f"/**/*{_case_insensitive_literal_pattern('.key')}",
    f"/**/*{_case_insensitive_literal_pattern('.p12')}",
    f"/**/*{_case_insensitive_literal_pattern('.pfx')}",
    f"/{_case_insensitive_literal_pattern('id_rsa')}",
    f"/{_case_insensitive_literal_pattern('id_ed25519')}",
    f"/**/{_case_insensitive_literal_pattern('id_rsa')}",
    f"/**/{_case_insensitive_literal_pattern('id_ed25519')}",
    *[
        f"/{_case_insensitive_literal_pattern(filename)}"
        for filename in _SECRET_LIKE_FILENAMES
    ],
    *[
        f"/**/{_case_insensitive_literal_pattern(filename)}"
        for filename in _SECRET_LIKE_FILENAMES
    ],
]
SENSITIVE_WRITE_DENY_PATHS = SENSITIVE_READ_DENY_PATHS
SHAPING_WRITABLE_ARTIFACT_FILENAMES = (
    "product-brief.md",
    "requirements.md",
    "prioritization.md",
    "architecture-brief.md",
    "decision-log.md",
    "task-breakdown.md",
    "readiness-gate.md",
)


def filesystem_permissions(
    mode: AgentMode,
    artifacts_dir: str = "docs/agent-workflow",
    implementation_write_paths: Iterable[str] = (),
    root_dir: str | Path | None = ".",
) -> list[FilesystemPermission]:
    """Return filesystem tool permissions for the selected mode."""

    safe_artifacts_dir = validate_artifacts_dir(artifacts_dir, root_dir)
    artifact_root = f"/{safe_artifacts_dir}"
    readiness_gate = f"{artifact_root}/{READINESS_GATE_FILENAME}"
    readiness_gate_deny_paths = _readiness_gate_deny_paths(readiness_gate)

    if mode == "implementation":
        permissions = [
            FilesystemPermission(operations=["read"], paths=SENSITIVE_READ_DENY_PATHS, mode="deny"),
            FilesystemPermission(operations=["read"], paths=["/**"], mode="allow"),
            FilesystemPermission(operations=["write"], paths=readiness_gate_deny_paths, mode="deny"),
            FilesystemPermission(operations=["write"], paths=SENSITIVE_WRITE_DENY_PATHS, mode="deny"),
        ]
        write_paths = normalize_implementation_write_paths(
            implementation_write_paths,
            root_dir=root_dir,
        )
        if write_paths:
            permissions.append(
                FilesystemPermission(
                    operations=["write"],
                    paths=write_paths,
                    mode="allow",
                )
            )
            permissions.append(FilesystemPermission(operations=["write"], paths=["/**"], mode="deny"))
        else:
            permissions.append(FilesystemPermission(operations=["write"], paths=["/**"], mode="allow"))
        return permissions

    return [
        FilesystemPermission(operations=["read"], paths=SENSITIVE_READ_DENY_PATHS, mode="deny"),
        FilesystemPermission(operations=["read"], paths=["/**"], mode="allow"),
        FilesystemPermission(operations=["write"], paths=readiness_gate_deny_paths, mode="deny"),
        FilesystemPermission(
            operations=["write"],
            paths=_shaping_artifact_write_paths(artifact_root),
            mode="allow",
        ),
        FilesystemPermission(operations=["write"], paths=["/**"], mode="deny"),
    ]


def _readiness_gate_deny_paths(readiness_gate: str) -> list[str]:
    return [readiness_gate, _case_insensitive_literal_pattern(readiness_gate)]


def _shaping_artifact_write_paths(artifact_root: str) -> list[str]:
    return [
        f"{artifact_root}/{filename}"
        for filename in SHAPING_WRITABLE_ARTIFACT_FILENAMES
    ]
