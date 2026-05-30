from __future__ import annotations

from collections.abc import Mapping


class RunnableConfigMetadataInjector:
    def inject(self, config: Mapping[str, object] | None, metadata: Mapping[str, object]) -> dict[str, object]:
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
        config: Mapping[str, object] | list[Mapping[str, object] | None] | None,
        metadata: Mapping[str, object],
    ) -> dict[str, object] | list[dict[str, object]]:
        if isinstance(config, list):
            return [self.inject(item, metadata) for item in config]
        return self.inject(config, metadata)

    def _scalar_metadata(self, metadata: Mapping[str, object]) -> dict[str, str | int | bool | float]:
        return {
            key: value
            for key, value in metadata.items()
            if isinstance(key, str) and isinstance(value, (str, int, bool, float))
        }
