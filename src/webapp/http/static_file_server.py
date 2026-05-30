from __future__ import annotations

import mimetypes
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler
from pathlib import Path
from urllib.parse import unquote


class StaticFileServer:
    def __init__(self, root_dir: Path | None = None) -> None:
        self._root_dir = (root_dir or Path(__file__).resolve().parents[1] / "static").resolve()

    def serve(self, handler: BaseHTTPRequestHandler, request_path: str) -> None:
        path = self._path_for(request_path)
        if path is None or not path.is_file():
            handler.send_error(HTTPStatus.NOT_FOUND, "Not found")
            return
        content = path.read_bytes()
        handler.send_response(HTTPStatus.OK)
        handler.send_header("Content-Type", mimetypes.guess_type(path.name)[0] or "application/octet-stream")
        handler.send_header("Content-Length", str(len(content)))
        handler.end_headers()
        handler.wfile.write(content)

    def _path_for(self, request_path: str) -> Path | None:
        relative = "index.html" if request_path in {"/", "/index.html"} else unquote(request_path).lstrip("/")
        candidate = (self._root_dir / relative).resolve()
        if candidate == self._root_dir or self._root_dir not in candidate.parents:
            return None
        return candidate
