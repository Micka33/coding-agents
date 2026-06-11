from __future__ import annotations

import sys
from pathlib import Path

import uvicorn

from src.team_instanciator.core.team_instanciator import TeamInstanciator
from src.type_defs import JsonObject
from src.webapp_studio.backend.api.studio_api_error import StudioApiError
from src.webapp_studio.backend.api.studio_session_controller import StudioSessionController
from src.webapp_studio.backend.server import create_app


class StudioBackendLauncher:
    def launch(
        self,
        *,
        team_file: str | Path | None = None,
        variables: JsonObject | None = None,
        config_variables: JsonObject | None = None,
        conversation_id: str | None = None,
        host: str = "127.0.0.1",
        port: int = 8765,
    ) -> None:
        try:
            controller = StudioSessionController(
                repository_root=Path(__file__).resolve().parents[4],
                workspace_dir=Path.cwd(),
                team_file=team_file,
                variables=variables,
                config_variables=config_variables,
                conversation_id=conversation_id,
                instanciator_factory=TeamInstanciator,
            )
        except StudioApiError as error:
            print(error.message, file=sys.stderr)
            raise SystemExit(1) from error
        message = controller.discovery_error_message()
        if message:
            print(message)
        app = create_app(controller)
        print(f"Webapp Studio backend: http://{host}:{port}")
        try:
            uvicorn.run(app, host=host, port=port)
        finally:
            controller.close()
