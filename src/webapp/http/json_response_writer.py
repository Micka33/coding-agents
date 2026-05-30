from __future__ import annotations

import json
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler

from src.type_defs import JsonValue


class JsonResponseWriter:
    def __init__(self, handler: BaseHTTPRequestHandler) -> None:
        self._handler = handler

    def send(self, value: JsonValue) -> None:
        payload = json.dumps(value, ensure_ascii=False).encode("utf-8")
        self._handler.send_response(HTTPStatus.OK)
        self._handler.send_header("Content-Type", "application/json; charset=utf-8")
        self._handler.send_header("Content-Length", str(len(payload)))
        self._handler.end_headers()
        self._handler.wfile.write(payload)
