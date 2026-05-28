from __future__ import annotations

from collections.abc import Mapping
from typing import Any


class RunnableConfigMetadataInjector:
    def inject(self, config: Mapping[str, Any] | None, metadata: Mapping[str, Any]) -> dict[str, Any]:
        updated = dict(config or {})
        existing_metadata = updated.get("metadata")
        merged_metadata = {
            **self._scalar_metadata(metadata),
            **self._scalar_metadata(existing_metadata if isinstance(existing_metadata, Mapping) else {}),
        }
        updated["metadata"] = merged_metadata
        return updated

    def inject_many(
        self,
        config: Mapping[str, Any] | list[Mapping[str, Any] | None] | None,
        metadata: Mapping[str, Any],
    ) -> dict[str, Any] | list[dict[str, Any]]:
        if isinstance(config, list):
            return [self.inject(item, metadata) for item in config]
        return self.inject(config, metadata)

    def _scalar_metadata(self, metadata: Mapping[str, Any]) -> dict[str, Any]:
        return {
            key: value
            for key, value in metadata.items()
            if isinstance(key, str) and isinstance(value, (str, int, bool, float))
        }
