from __future__ import annotations

from dataclasses import dataclass

from src.type_defs import JsonObject
from src.team_loader.errors.team_loader_error import TeamLoaderError
from src.team_loader.models._coercion import (
    as_json_object,
    optional_int,
    optional_string,
    string_tuple,
    string_value,
)


@dataclass(frozen=True)
class McpConfigValue:
    value: str | None = None
    env: str | None = None

    @classmethod
    def from_value(cls, value: object) -> McpConfigValue:
        if isinstance(value, str):
            return cls(value=value)
        mapping = as_json_object(value)
        if set(mapping) == {"env"} and isinstance(mapping["env"], str):
            return cls(env=mapping["env"])
        raise TeamLoaderError(f"Invalid MCP config value: {value!r}")


@dataclass(frozen=True)
class McpAuthDefinition:
    type: str
    env: str | None
    header: str | None
    factory: str | None
    args: JsonObject

    @classmethod
    def from_mapping(cls, value: object) -> McpAuthDefinition:
        mapping = as_json_object(value)
        return cls(
            type=string_value(mapping.get("type")),
            env=optional_string(mapping.get("env")),
            header=optional_string(mapping.get("header")),
            factory=optional_string(mapping.get("factory")),
            args=as_json_object(mapping.get("args")),
        )


@dataclass(frozen=True)
class McpServerDefinition:
    id: str
    transport: str
    command: str | None
    args: tuple[str, ...]
    url: str | None
    env: dict[str, McpConfigValue]
    headers: dict[str, McpConfigValue]
    auth: McpAuthDefinition | None
    timeout: int | None
    cwd: str | None
    exposes: tuple[str, ...] | None

    @classmethod
    def from_mapping(cls, server_id: str, value: object) -> McpServerDefinition:
        mapping = as_json_object(value)
        return cls(
            id=server_id,
            transport=cls._canonical_transport(string_value(mapping.get("transport"))),
            command=optional_string(mapping.get("command")),
            args=string_tuple(mapping.get("args")),
            url=optional_string(mapping.get("url")),
            env=cls._config_values(mapping.get("env")),
            headers=cls._config_values(mapping.get("headers")),
            auth=McpAuthDefinition.from_mapping(mapping.get("auth")) if "auth" in mapping else None,
            timeout=optional_int(mapping.get("timeout")),
            cwd=optional_string(mapping.get("cwd")),
            exposes=string_tuple(mapping.get("exposes")) if "exposes" in mapping else None,
        )

    @staticmethod
    def _canonical_transport(transport: str) -> str:
        return "streamable_http" if transport == "http" else transport

    @staticmethod
    def _config_values(value: object) -> dict[str, McpConfigValue]:
        return {key: McpConfigValue.from_value(item) for key, item in as_json_object(value).items()}
