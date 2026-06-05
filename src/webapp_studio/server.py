from __future__ import annotations

import argparse

from src.webapp_studio.application.studio_development_launcher import StudioDevelopmentLauncher
from src.webapp_studio.application.studio_server_args import StudioServerArgs


def parse_args(argv: list[str] | None = None) -> StudioServerArgs:
    parser = argparse.ArgumentParser(description="Serve Webapp Studio with backend and frontend processes.")
    parser.add_argument("team_file", nargs="?", help="Path to team.yaml.")
    parser.add_argument("--thread-id", help="Conversation id. Defaults to the team id.")
    parser.add_argument("--host", default="127.0.0.1", help="Host to bind.")
    parser.add_argument("--port", type=int, default=8765, help="Backend port to bind.")
    parser.add_argument("--frontend-port", type=int, default=3765, help="Next.js frontend port to bind.")
    parser.add_argument("--var", action="append", default=[], help="Template variable in key=value form. Repeatable.")
    parser.add_argument("--config", action="append", default=[], help="Runtime configuration in key=value form. Repeatable.")
    parser.add_argument("--openai-api-key", help="OpenAI API key passed as runtime configuration.")
    parser.add_argument("--tavily-api-key", help="Tavily API key passed as runtime configuration.")
    parser.add_argument("--env-file", help="Path to a .env file. Defaults to .env in the current working directory.")
    parser.add_argument("--no-env-file", action="store_true", help="Do not load a .env file from the current working directory.")
    args = parser.parse_args(argv)
    return StudioServerArgs(
        team_file=args.team_file,
        thread_id=args.thread_id,
        host=args.host,
        port=args.port,
        frontend_port=args.frontend_port,
        var=list(args.var),
        config=list(args.config),
        openai_api_key=args.openai_api_key,
        tavily_api_key=args.tavily_api_key,
        env_file=args.env_file,
        no_env_file=args.no_env_file,
    )


def main(argv: list[str] | None = None) -> int:
    StudioDevelopmentLauncher().launch_from_args(parse_args(argv))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
