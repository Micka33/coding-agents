from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import TypedDict

from src.type_defs import JsonObject, JsonValue, is_json_value
from src.team_instanciator.interfaces.cli_support import parse_key_value_pairs
from src.team_instanciator.configuration.dotenv_loader import DotEnvLoader
from src.team_instanciator.conversation.team import MentionAwareTeam
from src.team_instanciator.core.instantiated_team import InstantiatedTeam
from src.team_instanciator.core.team_instanciator import TeamInstanciator


class CliMessageDict(TypedDict):
    role: str
    name: str | None
    content: str
    tool_calls: JsonValue


class TeamInstanciatorCli:
    def main(self, argv: list[str] | None = None) -> int:
        raw_argv = list(sys.argv[1:] if argv is None else argv)
        if raw_argv and raw_argv[0] == "webapp":
            from src.webapp.server import main as webapp_main

            return webapp_main(raw_argv[1:])

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
        parser.add_argument("--no-webapp", action="store_true", help="Do not automatically launch the conversation web app.")
        parser.add_argument("--webapp-host", default="127.0.0.1", help="Host used for automatic conversation web app launch.")
        parser.add_argument("--webapp-port", type=int, default=8767, help="Port used for automatic conversation web app launch.")
        args = parser.parse_args(raw_argv)
        variables = self._variables(args.var)
        config_variables = self._config_variables(args)
        team = TeamInstanciator(config_variables=config_variables).instantiate(args.team_file, variables)
        try:
            if args.message:
                conversation = team.conversation_for(args.thread_id) if hasattr(team, "conversation_for") else None
                if conversation is not None:
                    self._print_conversation_result(conversation, args.message, args.json)
                else:
                    self._print_result(team, args.message, args.thread_id, args.json)
            elif getattr(team, "conversation", None) is not None and not args.no_webapp:
                team.close()
                from src.webapp_studio.application.studio_development_launcher import StudioDevelopmentLauncher

                StudioDevelopmentLauncher().launch(
                    team_file=args.team_file,
                    variables=variables,
                    config_variables=config_variables,
                    conversation_id=args.thread_id,
                    host=args.webapp_host,
                    backend_port=args.webapp_port,
                )
            else:
                self._print_summary(team, args.json)
        finally:
            team.close()
        return 0

    def _variables(self, raw_values: list[str]) -> JsonObject:
        return parse_key_value_pairs(raw_values)

    def _config_variables(self, args: argparse.Namespace) -> JsonObject:
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

    def _print_summary(self, instantiated_team: InstantiatedTeam, as_json: bool) -> None:
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

    def _print_result(self, instantiated_team: InstantiatedTeam, message: str, thread_id: str | None, as_json: bool) -> None:
        config = {"configurable": {"thread_id": thread_id or instantiated_team.team.id}}
        result = instantiated_team.invoke({"messages": [{"role": "user", "content": message}]}, config=config)
        messages = self._messages(result)
        if as_json:
            print(json.dumps({"messages": messages}, indent=2, ensure_ascii=False))
            return
        for message_item in messages:
            name = f" ({message_item['name']})" if message_item.get("name") else ""
            print(f"{message_item['role']}{name}: {message_item['content']}")

    def _print_conversation_result(self, conversation: MentionAwareTeam, message: str, as_json: bool) -> None:
        result = conversation.append_human_message(message, wait=True)
        state = conversation.state()
        added_events = [
            event
            for event in state["events"]
            if event["seq"] >= result.event.seq
        ]
        failures = [delivery.to_dict() for delivery in result.failures]
        if failures and not as_json:
            for failure in failures:
                print(
                    f"warning: delivery to {failure['agent_id']} ended with {failure['status']}: {failure.get('error') or ''}",
                    file=sys.stderr,
                )
        if as_json:
            print(
                json.dumps(
                    {
                        "event": result.event.to_dict(),
                        "events": added_events,
                        "deliveries": [delivery.to_dict() for delivery in result.deliveries],
                        "failures": failures,
                    },
                    indent=2,
                    ensure_ascii=False,
                )
            )
            return
        for event in added_events:
            print(f"{event['author_id']}: {event['content']}")

    def _messages(self, result: object) -> list[CliMessageDict]:
        raw_messages = result.get("messages", []) if isinstance(result, dict) else []
        return [self._message(raw_message) for raw_message in raw_messages]

    def _message(self, raw_message: object) -> CliMessageDict:
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
            "name": str(name) if name is not None else None,
            "content": "" if content is None else str(content),
            "tool_calls": tool_calls if tool_calls is not None and is_json_value(tool_calls) else [],
        }


def main(argv: list[str] | None = None) -> int:
    return TeamInstanciatorCli().main(argv)


if __name__ == "__main__":
    raise SystemExit(main())
