from __future__ import annotations

import os
import queue
import subprocess
import threading
import uuid
from pathlib import Path
from typing import Any

from src.webapp_studio.backend.api.time_utils import utc_now_iso


class StudioTerminalSession:
    def __init__(self, cwd: Path, *, columns: int = 100, rows: int = 30) -> None:
        self.session_id = f"term_{uuid.uuid4().hex}"
        self.cwd = cwd
        self.columns = columns
        self.rows = rows
        self.created_at = utc_now_iso()
        self._chunks: list[dict[str, Any]] = []
        self._lock = threading.Lock()
        self._output_queue: queue.Queue[bytes | None] = queue.Queue()
        self._process = subprocess.Popen(
            [os.environ.get("SHELL") or "/bin/sh", "-i"],
            cwd=str(cwd),
            env={**os.environ, "TERM": os.environ.get("TERM", "xterm-256color")},
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
        )
        self._append_output(f"Terminal started in {cwd}\n")
        self._reader = threading.Thread(target=self._read_output, daemon=True)
        self._reader.start()

    def snapshot(self) -> dict[str, Any]:
        return {
            "session_id": self.session_id,
            "cwd": str(self.cwd),
            "status": self.status(),
            "created_at": self.created_at,
            "columns": self.columns,
            "rows": self.rows,
        }

    def output_after(self, cursor: int) -> dict[str, Any]:
        self._drain_output()
        with self._lock:
            chunks = [chunk for chunk in self._chunks if int(chunk["cursor"]) > cursor]
            next_cursor = int(self._chunks[-1]["cursor"]) if self._chunks else cursor
        return {
            "session_id": self.session_id,
            "cursor": next_cursor,
            "chunks": chunks,
            "status": self.status(),
        }

    def write(self, data: str) -> dict[str, Any]:
        if self._process.poll() is not None:
            return self.snapshot()
        if self._process.stdin is not None:
            self._process.stdin.write(data.encode("utf-8", errors="replace"))
            self._process.stdin.flush()
        return self.snapshot()

    def resize(self, *, columns: int, rows: int) -> dict[str, Any]:
        self.columns = max(20, min(columns, 300))
        self.rows = max(5, min(rows, 120))
        return self.snapshot()

    def terminate(self) -> dict[str, Any]:
        if self._process.poll() is None:
            self._process.terminate()
            try:
                self._process.wait(timeout=1)
            except subprocess.TimeoutExpired:
                self._process.kill()
                self._process.wait(timeout=1)
        if self._process.stdin is not None:
            self._process.stdin.close()
        if self._process.stdout is not None:
            self._process.stdout.close()
        self._drain_output()
        return self.snapshot()

    def status(self) -> str:
        return "running" if self._process.poll() is None else "terminated"

    def _read_output(self) -> None:
        stream = self._process.stdout
        if stream is None:
            return
        descriptor = stream.fileno()
        while True:
            try:
                data = os.read(descriptor, 4096)
            except OSError:
                self._output_queue.put(None)
                return
            if not data:
                self._output_queue.put(None)
                return
            self._output_queue.put(data)

    def _drain_output(self) -> None:
        while True:
            try:
                data = self._output_queue.get_nowait()
            except queue.Empty:
                return
            if data is None:
                return
            self._append_output(data.decode("utf-8", errors="replace"))

    def _append_output(self, text: str) -> None:
        if not text:
            return
        with self._lock:
            self._chunks.append(
                {
                    "cursor": len(self._chunks) + 1,
                    "stream": "stdout",
                    "text": text,
                }
            )
