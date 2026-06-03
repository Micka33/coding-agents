from __future__ import annotations

from pathlib import Path

import uvicorn

from src.team_instanciator.core.team_instanciator import TeamInstanciator
from src.type_defs import JsonObject
from src.webapp_studio.backend.server import create_app


class StudioBackendLauncher:
    def launch(
        self,
        *,
        team_file: str | Path,
        variables: JsonObject | None = None,
        config_variables: JsonObject | None = None,
        conversation_id: str | None = None,
        host: str = "127.0.0.1",
        port: int = 8765,
    ) -> None:
        instantiated = TeamInstanciator(config_variables=config_variables).instantiate(team_file, variables)
        conversation = instantiated.conversation_for(conversation_id)
        if conversation is None:
            instantiated.close()
            raise ValueError("Selected team has no top-level conversation section.")

        app = create_app(conversation)
        print(f"Webapp Studio backend: http://{host}:{port}")
        try:
            uvicorn.run(app, host=host, port=port)
        finally:
            instantiated.close()
