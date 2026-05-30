from __future__ import annotations

from pathlib import Path

from src.team_instanciator.core.team_instanciator import TeamInstanciator
from src.type_defs import JsonObject
from src.webapp.http.conversation_request_handler import ConversationHTTPServer, ConversationRequestHandler

ThreadingHTTPServer = ConversationHTTPServer


class ConversationWebAppLauncher:
    def launch(
        self,
        *,
        team_file: str | Path,
        variables: JsonObject | None = None,
        config_variables: JsonObject | None = None,
        conversation_id: str | None = None,
        host: str = "127.0.0.1",
        port: int = 8767,
    ) -> None:
        instantiated = TeamInstanciator(config_variables=config_variables).instantiate(team_file, variables)
        conversation = instantiated.conversation_for(conversation_id)
        if conversation is None:
            instantiated.close()
            raise ValueError("Selected team has no top-level conversation section.")

        server = ThreadingHTTPServer((host, port), ConversationRequestHandler)
        server.instantiated_team = instantiated
        server.conversation = conversation
        print(f"Conversation web app: http://{host}:{port}")
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            pass
        finally:
            server.server_close()
            instantiated.close()
