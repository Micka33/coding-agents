from __future__ import annotations

from typing import Any, Literal, TypeAlias

CapabilityStatus: TypeAlias = Literal["available", "degraded", "unsupported", "planned"]
JsonLike: TypeAlias = Any
