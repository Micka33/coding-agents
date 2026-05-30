from __future__ import annotations

import json
from http.server import BaseHTTPRequestHandler

from src.type_defs import JsonObject, is_json_object


class JsonRequestReader:
    def __init__(self, handler: BaseHTTPRequestHandler) -> None:
        self._handler = handler

    def body(self) -> JsonObject:
        length = int(self._handler.headers.get("Content-Length") or "0")
        raw = self._handler.rfile.read(length) if length else b"{}"
        try:
            value: object = json.loads(raw.decode("utf-8"))
        except json.JSONDecodeError:
            return {}
        return value if is_json_object(value) else {}
