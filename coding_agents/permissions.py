"""Filesystem permissions for development-agent modes."""

from __future__ import annotations

from deepagents.middleware.filesystem import FilesystemPermission

from coding_agents.config import AgentMode


def filesystem_permissions(
    mode: AgentMode,
    artifacts_dir: str = "docs/agent-workflow",
) -> list[FilesystemPermission]:
    """Return filesystem tool permissions for the selected mode."""

    if mode == "implementation":
        return [
            FilesystemPermission(operations=["read"], paths=["/**"], mode="allow"),
            FilesystemPermission(operations=["write"], paths=["/**"], mode="allow"),
        ]

    artifact_root = "/" + artifacts_dir.strip("/")
    return [
        FilesystemPermission(operations=["read"], paths=["/**"], mode="allow"),
        FilesystemPermission(
            operations=["write"],
            paths=[artifact_root, f"{artifact_root}/**"],
            mode="allow",
        ),
        FilesystemPermission(operations=["write"], paths=["/**"], mode="deny"),
    ]
