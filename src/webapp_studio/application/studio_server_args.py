from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class StudioServerArgs:
    team_file: str | None
    thread_id: str | None
    host: str
    port: int
    frontend_port: int
    var: list[str]
    config: list[str]
    openai_api_key: str | None
    tavily_api_key: str | None
    env_file: str | None
    no_env_file: bool
