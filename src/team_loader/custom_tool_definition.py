from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class CustomToolDefinition:
    id: str
    factory: str
    args: dict[str, Any]
    exposes: tuple[str, ...]

    @classmethod
    def from_mapping(cls, custom_id: str, value: Any) -> CustomToolDefinition:
        mapping = value if isinstance(value, dict) else {}
        exposes = mapping.get("exposes", ())
        return cls(
            id=custom_id,
            factory=mapping.get("factory", ""),
            args=dict(mapping.get("args", {}) if isinstance(mapping.get("args"), dict) else {}),
            exposes=tuple(exposes if isinstance(exposes, list) else ()),
        )

    def validate_returned_tools(self, tool_names: list[str] | tuple[str, ...]) -> None:
        expected = set(self.exposes)
        actual = set(tool_names)
        if expected != actual:
            missing = sorted(expected - actual)
            extra = sorted(actual - expected)
            details = []
            if missing:
                details.append(f"missing: {', '.join(missing)}")
            if extra:
                details.append(f"extra: {', '.join(extra)}")
            raise ValueError(f"Custom tool '{self.id}' exposes mismatch ({'; '.join(details)}).")
