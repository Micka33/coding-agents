"""Small .env loader for local CLI and module usage."""

from __future__ import annotations

import os
from pathlib import Path


def load_dotenv_file(path: str | Path, *, override: bool = False) -> None:
    """Load simple KEY=VALUE pairs from a .env file.

    This intentionally supports the common local format without adding a runtime
    dependency. Existing environment variables win unless `override` is true.
    """

    env_path = Path(path)
    if not env_path.exists():
        return

    for raw_line in env_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue

        key, value = line.split("=", 1)
        key = key.strip()
        value = _strip_quotes(value.strip())
        if not key or (key in os.environ and not override):
            continue
        os.environ[key] = value


def _strip_quotes(value: str) -> str:
    if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
        return value[1:-1]
    return value
