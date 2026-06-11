from __future__ import annotations

import argparse
from dataclasses import dataclass

from src.team_instanciator.interfaces.cli_support import build_config_variables, parse_key_value_pairs
from src.webapp.application.conversation_web_app_launcher import ConversationWebAppLauncher


@dataclass(frozen=True)
class ServerArgs:
    team_file: str
    thread_id: str | None
    host: str
    port: int
    var: list[str]
    config: list[str]
    openai_api_key: str | None
    tavily_api_key: str | None
    env_file: str | None
    no_env_file: bool


def parse_args(argv: list[str] | None = None) -> ServerArgs:
    parser = argparse.ArgumentParser(description="Serve the mention-router conversation web app.")
    parser.add_argument("team_file", help="Path to team.yaml.")
    parser.add_argument("--thread-id", help="Conversation id. Defaults to the team id.")
    parser.add_argument("--host", default="127.0.0.1", help="Host to bind.")
    parser.add_argument("--port", type=int, default=8767, help="Port to bind.")
    parser.add_argument("--var", action="append", default=[], help="Template variable in key=value form. Repeatable.")
    parser.add_argument("--config", action="append", default=[], help="Runtime configuration in key=value form. Repeatable.")
    parser.add_argument("--openai-api-key", help="OpenAI API key passed as runtime configuration.")
    parser.add_argument("--tavily-api-key", help="Tavily API key passed as runtime configuration.")
    parser.add_argument("--env-file", help="Path to a .env file. Defaults to .env in the current working directory.")
    parser.add_argument("--no-env-file", action="store_true", help="Do not load a .env file from the current working directory.")
    args = parser.parse_args(argv)
    return ServerArgs(
        team_file=args.team_file,
        thread_id=args.thread_id,
        host=args.host,
        port=args.port,
        var=list(args.var),
        config=list(args.config),
        openai_api_key=args.openai_api_key,
        tavily_api_key=args.tavily_api_key,
        env_file=args.env_file,
        no_env_file=args.no_env_file,
    )


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    ConversationWebAppLauncher().launch(
        team_file=args.team_file,
        variables=parse_key_value_pairs(args.var),
        config_variables=build_config_variables(args),
        conversation_id=args.thread_id,
        host=args.host,
        port=args.port,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
