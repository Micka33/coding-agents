from __future__ import annotations

from dataclasses import dataclass

from src.team_loader.models._coercion import as_json_object, optional_string


@dataclass(frozen=True)
class CheckpointerDefault:
    env: str | None
    default: str | None
    sqlite_path_env: str | None
    sqlite_path_default: str | None
    postgres_url_env: tuple[str, ...]
    postgres_url_default: str | None

    @classmethod
    def from_mapping(cls, value: object) -> CheckpointerDefault:
        mapping = as_json_object(value)
        sqlite_path = as_json_object(mapping.get("sqlite_path"))
        postgres_url = as_json_object(mapping.get("postgres_url"))
        env_values = postgres_url.get("env", ())
        if isinstance(env_values, str):
            env_values = (env_values,)
        elif isinstance(env_values, list):
            env_values = tuple(str(item) for item in env_values if item)
        else:
            env_values = ()
        return cls(
            env=optional_string(mapping.get("env")),
            default=optional_string(mapping.get("default")),
            sqlite_path_env=optional_string(sqlite_path.get("env")),
            sqlite_path_default=optional_string(sqlite_path.get("default")),
            postgres_url_env=tuple(env_values or ()),
            postgres_url_default=optional_string(postgres_url.get("default")),
        )
