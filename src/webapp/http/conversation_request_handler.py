from __future__ import annotations

from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import cast
from urllib.parse import urlparse

from src.team_instanciator.core.instantiated_team import InstantiatedTeam
from src.webapp.api.conversation_api_controller import ConversationApiController
from src.webapp.api.conversation_protocol import WebConversation
from src.webapp.http.json_request_reader import JsonRequestReader
from src.webapp.http.json_response_writer import JsonResponseWriter
from src.webapp.http.static_file_server import StaticFileServer


class ConversationHTTPServer(ThreadingHTTPServer):
    instantiated_team: InstantiatedTeam
    conversation: WebConversation


class ConversationRequestHandler(BaseHTTPRequestHandler):
    server_version = "ConversationWebApp/0.1"

    def do_GET(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        if parsed.path == "/api/state":
            self._json_writer().send(self._api().state())
            return
        if parsed.path == "/api/activity":
            self._json_writer().send(self._api().activity(parsed.query))
            return
        self._static_files().serve(self, parsed.path)

    def do_POST(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        if parsed.path == "/api/messages":
            self._json_writer().send(self._api().append_message(self._json_reader().body()))
            return
        if parsed.path == "/api/runtime":
            self._json_writer().send(self._api().update_runtime(self._json_reader().body()))
            return
        if parsed.path == "/api/stop":
            self._stop_agent()
            return
        self.send_error(HTTPStatus.NOT_FOUND, "Not found")

    def _stop_agent(self) -> None:
        try:
            self._json_writer().send(self._api().stop_agent(self._json_reader().body()))
        except ValueError as exc:
            self.send_error(HTTPStatus.BAD_REQUEST, str(exc))

    def _api(self) -> ConversationApiController:
        return ConversationApiController(cast(ConversationHTTPServer, self.server).conversation)

    def _json_reader(self) -> JsonRequestReader:
        return JsonRequestReader(self)

    def _json_writer(self) -> JsonResponseWriter:
        return JsonResponseWriter(self)

    def _static_files(self) -> StaticFileServer:
        return StaticFileServer()

    def log_message(self, format: str, *args: object) -> None:
        return
