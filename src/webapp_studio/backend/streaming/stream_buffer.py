from __future__ import annotations

from collections import deque
from threading import Lock

from src.webapp_studio.backend.contracts.stream_frame import StreamFrame
from src.webapp_studio.backend.contracts.types import JsonLike


class StreamBuffer:
    def __init__(self, *, max_frames: int = 500) -> None:
        self._frames: deque[StreamFrame] = deque(maxlen=max_frames)
        self._lock = Lock()
        self._sequence = 0

    def publish(self, event: str, payload: JsonLike | None = None) -> StreamFrame:
        with self._lock:
            self._sequence += 1
            frame = StreamFrame(
                id=f"stream_{self._sequence:08d}",
                event=event,
                cursor=f"event_seq:{self._sequence}",
                payload={} if payload is None else payload,
            )
            self._frames.append(frame)
            return frame

    def replay_after(self, cursor: str | None) -> list[StreamFrame] | None:
        with self._lock:
            frames = list(self._frames)
        if cursor is None:
            return frames
        sequence = self._parse_sequence(cursor)
        if sequence is None:
            return None
        if frames and sequence < (self._parse_sequence(frames[0].cursor) or 0):
            return None
        replay = [frame for frame in frames if self._parse_sequence(frame.cursor) is not None and self._parse_sequence(frame.cursor) > sequence]
        return replay

    def latest_cursor(self) -> str | None:
        with self._lock:
            return self._frames[-1].cursor if self._frames else None

    def _parse_sequence(self, cursor_or_event_id: str) -> int | None:
        if cursor_or_event_id.startswith("stream_"):
            return self._parse_int(cursor_or_event_id.removeprefix("stream_"))
        if not cursor_or_event_id.startswith("event_seq:"):
            return None
        return self._parse_int(cursor_or_event_id.removeprefix("event_seq:"))

    def _parse_int(self, value: str) -> int | None:
        try:
            return int(value)
        except ValueError:
            return None
