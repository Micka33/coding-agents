from __future__ import annotations

from importlib import metadata
from pathlib import Path
import tomllib


def current_coding_agents_version() -> str:
    try:
        return metadata.version("coding-agents")
    except metadata.PackageNotFoundError:
        pyproject = Path(__file__).resolve().parents[2] / "pyproject.toml"
        try:
            data = tomllib.loads(pyproject.read_text(encoding="utf-8"))
        except OSError:
            return "0.0.0"
        project = data.get("project")
        if isinstance(project, dict) and isinstance(project.get("version"), str):
            return project["version"]
        return "0.0.0"
