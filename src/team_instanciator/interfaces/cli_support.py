from __future__ import annotations

from pathlib import Path
from collections.abc import Sequence
from typing import Protocol

from src.team_instanciator.configuration.dotenv_loader import DotEnvLoader
from src.type_defs import JsonObject


class RuntimeConfigArgs(Protocol):
    config: Sequence[str]
    openai_api_key: str | None
    tavily_api_key: str | None
    env_file: str | None
    no_env_file: bool


def parse_key_value_pairs(raw_values: Sequence[str]) -> JsonObject:
    values: JsonObject = {}
    for raw in raw_values:
        key, separator, value = raw.partition("=")
        if separator:
            values[key] = value
    return values


def build_config_variables(args: RuntimeConfigArgs) -> JsonObject:
    config_variables: JsonObject = {}
    if not args.no_env_file:
        dotenv_path = Path(args.env_file) if args.env_file else Path.cwd() / ".env"
        config_variables.update(DotEnvLoader().load(dotenv_path))
    config_variables.update(parse_key_value_pairs(args.config))
    if args.openai_api_key:
        config_variables["openai_api_key"] = args.openai_api_key
    if args.tavily_api_key:
        config_variables["tavily_api_key"] = args.tavily_api_key
    return config_variables
