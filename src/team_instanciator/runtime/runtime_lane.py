from __future__ import annotations

from dataclasses import dataclass
from typing import NotRequired, TypedDict


class RuntimeLaneDict(TypedDict):
    lane_id: str
    kind: str
    agent_id: str | None
    agent_name: str | None
    source_agent_id: str | None
    target_agent_id: str | None
    tool_name: str | None
    thread_id_pattern: str | None
    thread_id: NotRequired[str | None]


@dataclass(frozen=True)
class RuntimeLane:
    lane_id: str
    kind: str
    agent_id: str | None
    agent_name: str | None
    source_agent_id: str | None = None
    target_agent_id: str | None = None
    tool_name: str | None = None
    thread_id_pattern: str | None = None

    def to_dict(self, parent_thread_id: str | None = None) -> RuntimeLaneDict:
        data: RuntimeLaneDict = {
            "lane_id": self.lane_id,
            "kind": self.kind,
            "agent_id": self.agent_id,
            "agent_name": self.agent_name,
            "source_agent_id": self.source_agent_id,
            "target_agent_id": self.target_agent_id,
            "tool_name": self.tool_name,
            "thread_id_pattern": self.thread_id_pattern,
        }
        if parent_thread_id is not None:
            data["thread_id"] = self.thread_id(parent_thread_id)
        return data

    def thread_id(self, parent_thread_id: str) -> str | None:
        if self.kind == "entrypoint":
            return parent_thread_id
        if self.thread_id_pattern is None:
            return None
        return self.thread_id_pattern.replace("{parent_thread_id}", parent_thread_id)
