from __future__ import annotations

import os
from typing import Any


class RuntimeConfiguration:
    _PROVIDER_API_KEYS = {
        "anthropic": ("ANTHROPIC_API_KEY",),
        "cohere": ("COHERE_API_KEY",),
        "fireworks": ("FIREWORKS_API_KEY",),
        "google": ("GOOGLE_API_KEY",),
        "google_genai": ("GOOGLE_API_KEY",),
        "groq": ("GROQ_API_KEY",),
        "mistral": ("MISTRAL_API_KEY",),
        "mistralai": ("MISTRAL_API_KEY",),
        "openai": ("OPENAI_API_KEY",),
        "together": ("TOGETHER_API_KEY",),
    }
    _TOOL_API_KEYS = {
        "tavily": ("TAVILY_API_KEY",),
    }

    def __init__(self, values: dict[str, Any] | None = None) -> None:
        self._values = dict(values or {})
        self._normalized_values = {self._normalize(key): value for key, value in self._values.items()}

    def merge(self, values: dict[str, Any] | RuntimeConfiguration | None) -> RuntimeConfiguration:
        merged = self.as_dict()
        if isinstance(values, RuntimeConfiguration):
            merged.update(values.as_dict())
        elif values:
            merged.update(values)
        return RuntimeConfiguration(merged)

    def as_dict(self) -> dict[str, Any]:
        return dict(self._values)

    def get(self, key: str, default: Any = None) -> Any:
        normalized = self._normalize(key)
        if normalized in self._normalized_values:
            return self._normalized_values[normalized]
        if key in os.environ:
            return os.environ[key]
        if normalized in os.environ:
            return os.environ[normalized]
        return default

    def model_kwargs(self, model: str) -> dict[str, Any]:
        provider = self._provider(model)
        api_key = self._api_key(provider)
        if api_key is None:
            return {}
        return {"api_key": api_key}

    def tool_api_key(self, tool_provider: str) -> Any:
        for key in self._TOOL_API_KEYS.get(self._normalize(tool_provider).lower(), ()):
            value = self.get(key)
            if value:
                return value
        return None

    def _api_key(self, provider: str | None) -> Any:
        generic = self.get("API_KEY")
        if generic:
            return generic
        for key in self._PROVIDER_API_KEYS.get(provider or "", ()):
            value = self.get(key)
            if value:
                return value
        return None

    def _provider(self, model: str) -> str | None:
        provider, separator, _ = model.partition(":")
        if not separator:
            return None
        return self._normalize(provider).lower()

    def _normalize(self, key: str) -> str:
        normalized = []
        for character in key:
            if character.isalnum():
                normalized.append(character.upper())
            else:
                normalized.append("_")
        return "".join(normalized)
