"""Deep Agents harness-profile safety configuration."""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from deepagents import GeneralPurposeSubagentProfile, HarnessProfile, register_harness_profile
from langchain_core.language_models.chat_models import BaseChatModel

_DISABLE_GENERAL_PURPOSE_PROFILE = HarnessProfile(
    general_purpose_subagent=GeneralPurposeSubagentProfile(enabled=False)
)


def disable_default_general_purpose_subagent(model: str | BaseChatModel) -> None:
    """Disable DeepAgents' auto-added ``general-purpose`` subagent for a model.

    DeepAgents controls the default subagent through harness profiles rather than
    a direct ``create_deep_agent`` argument. Register both exact model keys and a
    provider fallback when they can be derived so manager and resident agents do
    not receive an unintended broad-purpose delegate.
    """

    for key in _candidate_profile_keys(model):
        if _is_valid_profile_key(key):
            register_harness_profile(key, _DISABLE_GENERAL_PURPOSE_PROFILE)


def _candidate_profile_keys(model: str | BaseChatModel) -> tuple[str, ...]:
    if isinstance(model, str):
        return _dedupe(_string_model_keys(model))
    return _dedupe(_chat_model_keys(model))


def _string_model_keys(model: str) -> Iterable[str]:
    spec = model.strip()
    if not spec:
        return ()
    if ":" in spec:
        provider, _separator, _model_name = spec.partition(":")
        return (spec, provider) if provider else (spec,)
    return (spec,)


def _chat_model_keys(model: BaseChatModel) -> Iterable[str]:
    provider, identifier = _model_provider_and_identifier(model)
    keys: list[str] = []
    if provider and identifier and ":" not in identifier:
        keys.append(f"{provider}:{identifier}")
    if identifier and ":" in identifier:
        keys.append(identifier)
    if provider:
        keys.append(provider)
    return keys


def _model_provider_and_identifier(model: BaseChatModel) -> tuple[str | None, str | None]:
    try:
        from deepagents._models import get_model_identifier, get_model_provider  # noqa: PLC0415
    except Exception:  # pragma: no cover - private DeepAgents API fallback
        return _fallback_model_provider_and_identifier(model)

    try:
        provider = get_model_provider(model)
        identifier = get_model_identifier(model)
    except Exception:  # pragma: no cover - defensive around provider-specific models
        return _fallback_model_provider_and_identifier(model)
    return _clean_key_part(provider), _clean_key_part(identifier)


def _fallback_model_provider_and_identifier(model: BaseChatModel) -> tuple[str | None, str | None]:
    provider = _clean_key_part(getattr(model, "model_provider", None))
    identifier = _clean_key_part(
        getattr(model, "model_name", None)
        or getattr(model, "model", None)
        or getattr(model, "model_id", None)
    )

    if provider or identifier:
        return provider, identifier

    try:
        params: dict[str, Any] = model._get_ls_params()  # noqa: SLF001 - public LangSmith hook in LangChain models
    except Exception:  # pragma: no cover - model implementations vary
        return None, None

    return _clean_key_part(params.get("ls_provider")), _clean_key_part(params.get("ls_model_name"))


def _clean_key_part(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    stripped = value.strip()
    return stripped or None


def _is_valid_profile_key(key: str) -> bool:
    if not key or key != key.strip() or key.count(":") > 1:
        return False
    if ":" not in key:
        return True
    provider, _separator, model = key.partition(":")
    return bool(provider and model and provider == provider.strip() and model == model.strip())


def _dedupe(values: Iterable[str]) -> tuple[str, ...]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        result.append(value)
    return tuple(result)
