from __future__ import annotations

import os
from collections.abc import Iterable, Mapping

from src.team_instanciator.configuration.runtime_configuration import RuntimeConfiguration


class EnvView(Mapping[str, object]):
    """Read-only environment view backed by runtime configuration and os.environ."""

    def __init__(self, configuration: RuntimeConfiguration) -> None:
        self._configuration = configuration

    def get(self, key: str, default: object = None) -> object:
        return self._configuration.get(key, default)

    def require(self, key: str) -> object:
        value = self.get(key)
        if value is None or value == "":
            raise KeyError(f"Missing required environment value: {key}")
        return value

    def as_dict(self, names: Iterable[str] | None = None) -> dict[str, object]:
        if names is not None:
            return {name: self.get(name) for name in names if self.get(name) is not None}
        values = dict(os.environ)
        values.update(self._configuration.as_dict())
        return values

    def __getitem__(self, key: str) -> object:
        missing = object()
        value = self.get(key, missing)
        if value is missing:
            raise KeyError(key)
        return value

    def __iter__(self):
        yield from self.as_dict()

    def __len__(self) -> int:
        return len(self.as_dict())
