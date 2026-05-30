from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from .dotenv_loader import DotEnvLoader
from .team_instanciator import TeamInstanciator


class TeamInstanciatorCli:
    def main(self, argv: list[str] | None = None) -> int:
        parser = argparse.ArgumentParser(description="Instantiate a team graph from team.yaml.")
        parser.add_argument("team_file", help="Path to team.yaml.")
        parser.add_argument("--var", action="append", default=[], help="Template variable in key=value form. Repeatable.")
        parser.add_argument("--config", action="append", default=[], help="Runtime configuration in key=value form. Repeatable.")
        parser.add_argument("--openai-api-key", help="OpenAI API key passed as runtime configuration.")
        parser.add_argument("--tavily-api-key", help="Tavily API key passed as runtime configuration.")
        parser.add_argument("--env-file", help="Path to a .env file. Defaults to .env in the current working directory.")
        parser.add_argument("--no-env-file", action="store_true", help="Do not load a .env file from the current working directory.")
        parser.add_argument("--message", help="Invoke the entrypoint with this user message after instantiation.")
        parser.add_argument("--thread-id", help="Thread id used when invoking with --message.")
        parser.add_argument("--json", action="store_true", help="Print a JSON summary.")
        args = parser.parse_args(argv)
        variables = self._variables(args.var)
        config_variables = self._config_variables(args)
        team = TeamInstanciator(config_variables=config_variables).instantiate(args.team_file, variables)
        try:
            if args.message:
                self._print_result(team, args.message, args.thread_id, args.json)
            else:
                self._print_summary(team, args.json)
        finally:
            team.close()
        return 0

    def _variables(self, raw_values: list[str]) -> dict[str, Any]:
        variables: dict[str, Any] = {}
        for raw in raw_values:
            key, separator, value = raw.partition("=")
            if separator:
                variables[key] = value
        return variables

    def _config_variables(self, args: argparse.Namespace) -> dict[str, Any]:
        config_variables = self._dotenv_variables(args)
        config_variables.update(self._variables(args.config))
        if args.openai_api_key:
            config_variables["openai_api_key"] = args.openai_api_key
        if args.tavily_api_key:
            config_variables["tavily_api_key"] = args.tavily_api_key
        return config_variables

    def _dotenv_variables(self, args: argparse.Namespace) -> dict[str, str]:
        if args.no_env_file:
            return {}
        dotenv_path = Path(args.env_file) if args.env_file else Path.cwd() / ".env"
        return DotEnvLoader().load(dotenv_path)

    def _print_summary(self, instantiated_team: Any, as_json: bool) -> None:
        summary = {
            "team": instantiated_team.team.id,
            "entrypoint": instantiated_team.team.entrypoint().id if instantiated_team.team.entrypoint() else None,
            "agents": sorted(instantiated_team.team.agents),
            "relations": len(instantiated_team.team.relations),
        }
        if as_json:
            print(json.dumps(summary, indent=2))
        else:
            print(f"Team: {summary['team']}")
            print(f"Entrypoint: {summary['entrypoint']}")
            print(f"Agents: {', '.join(summary['agents'])}")
            print(f"Relations: {summary['relations']}")

    def _print_result(self, instantiated_team: Any, message: str, thread_id: str | None, as_json: bool) -> None:
        config = {"configurable": {"thread_id": thread_id or instantiated_team.team.id}}
        result = instantiated_team.invoke({"messages": [{"role": "user", "content": message}]}, config=config)
        messages = self._messages(result)
        if as_json:
            print(json.dumps({"messages": messages}, indent=2, ensure_ascii=False))
            return
        for message_item in messages:
            name = f" ({message_item['name']})" if message_item.get("name") else ""
            print(f"{message_item['role']}{name}: {message_item['content']}")

    def _messages(self, result: Any) -> list[dict[str, str]]:
        raw_messages = result.get("messages", []) if isinstance(result, dict) else []
        return [self._message(raw_message) for raw_message in raw_messages]

    def _message(self, raw_message: Any) -> dict[str, Any]:
        role = getattr(raw_message, "type", None)
        name = getattr(raw_message, "name", None)
        content = getattr(raw_message, "content", None)
        tool_calls = getattr(raw_message, "tool_calls", None)
        if isinstance(raw_message, dict):
            role = raw_message.get("role", role)
            name = raw_message.get("name", name)
            content = raw_message.get("content", content)
            tool_calls = raw_message.get("tool_calls", tool_calls)
        return {
            "role": str(role or "message"),
            "name": name,
            "content": "" if content is None else str(content),
            "tool_calls": tool_calls or [],
        }


def main(argv: list[str] | None = None) -> int:
    return TeamInstanciatorCli().main(argv)


if __name__ == "__main__":
    raise SystemExit(main())
