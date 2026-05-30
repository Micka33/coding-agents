from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class CheckpointerDefault:
    env: str | None
    default: str | None
    sqlite_path_env: str | None
    sqlite_path_default: str | None
    postgres_url_env: tuple[str, ...]
    postgres_url_default: str | None

    @classmethod
    def from_mapping(cls, value: Any) -> CheckpointerDefault:
        mapping = value if isinstance(value, dict) else {}
        sqlite_path = mapping.get("sqlite_path") if isinstance(mapping.get("sqlite_path"), dict) else {}
        postgres_url = mapping.get("postgres_url") if isinstance(mapping.get("postgres_url"), dict) else {}
        env_values = postgres_url.get("env", ())
        if isinstance(env_values, str):
            env_values = (env_values,)
        return cls(
            env=mapping.get("env"),
            default=mapping.get("default"),
            sqlite_path_env=sqlite_path.get("env"),
            sqlite_path_default=sqlite_path.get("default"),
            postgres_url_env=tuple(env_values or ()),
            postgres_url_default=postgres_url.get("default"),
        )
