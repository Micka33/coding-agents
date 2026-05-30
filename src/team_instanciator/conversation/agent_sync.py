from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class AgentSync:
    messages: list[object]
    snapshot_seq: int
    token_estimate: int
    identity_inserted: bool
    projected_event_count: int
