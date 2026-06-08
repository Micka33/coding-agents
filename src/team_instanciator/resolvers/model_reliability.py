from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Literal

from langchain_core.language_models.chat_models import BaseChatModel

from src.team_instanciator.configuration.runtime_configuration import RuntimeConfiguration


LOGGER = logging.getLogger(__name__)
_REQUEST_TIMEOUT_PROVIDERS = {"anthropic"}

ModelFailureCode = Literal[
    "stream_idle_timeout",
    "network_error",
    "rate_limited",
    "server_error",
    "temporary_unavailable",
    "provider_error",
]
TimeoutMode = Literal["stream_idle_timeout", "non_streaming_timeout"]


@dataclass(frozen=True)
class ModelReliabilityPolicy:
    stream_idle_timeout_s: float = 120.0
    max_attempts: int = 3
    retry_backoff_initial_s: float = 1.0
    retry_backoff_max_s: float = 20.0

    @classmethod
    def from_configuration(cls, configuration: RuntimeConfiguration) -> ModelReliabilityPolicy:
        return cls(
            stream_idle_timeout_s=_float_setting(
                configuration,
                "CODING_AGENTS_MODEL_STREAM_IDLE_TIMEOUT_S",
                default=120.0,
                allow_zero=True,
            ),
            max_attempts=_max_attempts_setting(configuration),
            retry_backoff_initial_s=_float_setting(
                configuration,
                "CODING_AGENTS_MODEL_RETRY_BACKOFF_INITIAL_S",
                default=1.0,
                allow_zero=True,
            ),
            retry_backoff_max_s=_float_setting(
                configuration,
                "CODING_AGENTS_MODEL_RETRY_BACKOFF_MAX_S",
                default=20.0,
                allow_zero=True,
            ),
        )


@dataclass(frozen=True)
class ModelProviderCapabilities:
    provider: str
    supports_stream_idle_timeout: bool
    timeout_mode: TimeoutMode


@dataclass(frozen=True)
class ModelExceptionClassification:
    retryable: bool
    failure_code: ModelFailureCode
    provider_error_type: str


class ReliableChatModel(BaseChatModel):
    wrapped_model: BaseChatModel
    policy: ModelReliabilityPolicy
    capabilities: ModelProviderCapabilities
    resolved_model_name: str

    @property
    def _llm_type(self) -> str:
        wrapped_type = getattr(self.wrapped_model, "_llm_type", self.capabilities.provider)
        return f"reliable:{wrapped_type}"

    @property
    def _identifying_params(self) -> dict[str, Any]:
        return {
            "model": self.resolved_model_name,
            "provider": self.capabilities.provider,
            "max_attempts": self.policy.max_attempts,
            "timeout_mode": self.capabilities.timeout_mode,
            "timeout_seconds": self.policy.stream_idle_timeout_s,
        }

    @property
    def model_name(self) -> str:
        value = getattr(self.wrapped_model, "model_name", None)
        return str(value) if value else self.resolved_model_name

    @property
    def model(self) -> str:
        value = getattr(self.wrapped_model, "model", None)
        return str(value) if value else self.resolved_model_name

    @property
    def model_id(self) -> str:
        value = getattr(self.wrapped_model, "model_id", None)
        return str(value) if value else self.resolved_model_name

    @property
    def profile(self) -> dict[str, Any] | None:
        value = getattr(self.wrapped_model, "profile", None)
        return value if isinstance(value, dict) else None

    def bind(self, **kwargs: Any) -> Any:
        return self._wrap_runnable(self.wrapped_model.bind(**kwargs))

    def bind_tools(self, tools: Any, *, tool_choice: Any = None, **kwargs: Any) -> Any:
        if tool_choice is None:
            return self._wrap_runnable(self.wrapped_model.bind_tools(tools, **kwargs))
        return self._wrap_runnable(self.wrapped_model.bind_tools(tools, tool_choice=tool_choice, **kwargs))

    def invoke(self, input: Any, config: Any = None, *, stop: list[str] | None = None, **kwargs: Any) -> Any:
        return self._wrap_runnable(self.wrapped_model).invoke(input, config=config, stop=stop, **kwargs)

    async def ainvoke(self, input: Any, config: Any = None, *, stop: list[str] | None = None, **kwargs: Any) -> Any:
        return await self._wrap_runnable(self.wrapped_model).ainvoke(input, config=config, stop=stop, **kwargs)

    def stream(self, input: Any, config: Any = None, *, stop: list[str] | None = None, **kwargs: Any) -> Any:
        yield from self._wrap_runnable(self.wrapped_model).stream(input, config=config, stop=stop, **kwargs)

    async def astream(self, input: Any, config: Any = None, *, stop: list[str] | None = None, **kwargs: Any) -> Any:
        async for chunk in self._wrap_runnable(self.wrapped_model).astream(input, config=config, stop=stop, **kwargs):
            yield chunk

    def _generate(self, messages: list[Any], stop: list[str] | None = None, run_manager: Any = None, **kwargs: Any) -> Any:
        return self.wrapped_model._generate(messages, stop=stop, run_manager=run_manager, **kwargs)

    async def _agenerate(self, messages: list[Any], stop: list[str] | None = None, run_manager: Any = None, **kwargs: Any) -> Any:
        return await self.wrapped_model._agenerate(messages, stop=stop, run_manager=run_manager, **kwargs)

    def _wrap_runnable(self, runnable: Any) -> Any:
        configured = runnable.with_config(metadata=self._reliability_metadata()) if hasattr(runnable, "with_config") else runnable
        if self.policy.max_attempts <= 1 or not hasattr(configured, "with_retry"):
            return configured
        return configured.with_retry(
            retry_if_exception_type=retryable_model_exception_types(),
            wait_exponential_jitter=True,
            exponential_jitter_params={
                "initial": self.policy.retry_backoff_initial_s,
                "max": self.policy.retry_backoff_max_s,
                "exp_base": 2.0,
                "jitter": 1.0,
            },
            stop_after_attempt=self.policy.max_attempts,
        )

    def _reliability_metadata(self) -> dict[str, str | int | float | bool]:
        return {
            "model_provider": self.capabilities.provider,
            "model_name": self.resolved_model_name,
            "model_reliability_max_attempts": self.policy.max_attempts,
            "model_reliability_timeout_mode": self.capabilities.timeout_mode,
            "model_reliability_timeout_s": self.policy.stream_idle_timeout_s,
            "model_reliability_stream_idle_timeout": self.capabilities.supports_stream_idle_timeout,
        }


def provider_capabilities(model: str) -> ModelProviderCapabilities:
    provider = provider_name(model)
    if provider == "openai":
        return ModelProviderCapabilities(
            provider=provider,
            supports_stream_idle_timeout=True,
            timeout_mode="stream_idle_timeout",
        )
    return ModelProviderCapabilities(
        provider=provider,
        supports_stream_idle_timeout=False,
        timeout_mode="non_streaming_timeout",
    )


def provider_name(model: str) -> str:
    provider, separator, _model_name = model.partition(":")
    if separator:
        return provider.lower()
    if model.startswith(("gpt-", "chatgpt-", "o1", "o3", "o4")):
        return "openai"
    return "unknown"


def reliability_init_kwargs(model: str, policy: ModelReliabilityPolicy) -> dict[str, object]:
    capabilities = provider_capabilities(model)
    if capabilities.provider != "openai":
        if capabilities.provider in _REQUEST_TIMEOUT_PROVIDERS:
            return {
                "timeout": None if policy.stream_idle_timeout_s == 0 else policy.stream_idle_timeout_s,
                "max_retries": 0,
            }
        return {}
    return {
        "streaming": True,
        "stream_chunk_timeout": policy.stream_idle_timeout_s,
        "max_retries": 0,
    }


def wrap_model_for_reliability(model: object, *, model_name: str, policy: ModelReliabilityPolicy) -> object:
    if not isinstance(model, BaseChatModel):
        LOGGER.warning("Model %s is not a BaseChatModel; model reliability wrapper was not applied.", model_name)
        return model
    return ReliableChatModel(
        wrapped_model=model,
        policy=policy,
        capabilities=provider_capabilities(model_name),
        resolved_model_name=model_name,
    )


def classify_model_exception(error: BaseException) -> ModelExceptionClassification:
    error_type = error.__class__.__name__
    if isinstance(error, TimeoutError):
        return ModelExceptionClassification(True, "stream_idle_timeout", error_type)
    if isinstance(error, ConnectionError):
        return ModelExceptionClassification(True, "network_error", error_type)
    if _is_retryable_provider_error(error):
        return ModelExceptionClassification(True, _provider_failure_code(error), error_type)
    return ModelExceptionClassification(False, "provider_error", error_type)


def retryable_model_exception_types() -> tuple[type[BaseException], ...]:
    types: list[type[BaseException]] = [TimeoutError, ConnectionError]
    try:
        import openai
    except ImportError:
        openai = None
    if openai is not None:
        for name in ("APIConnectionError", "APITimeoutError", "RateLimitError", "InternalServerError"):
            error_type = getattr(openai, name, None)
            if isinstance(error_type, type) and issubclass(error_type, BaseException):
                types.append(error_type)
    return tuple(dict.fromkeys(types))


def _float_setting(
    configuration: RuntimeConfiguration,
    key: str,
    *,
    default: float,
    allow_zero: bool,
) -> float:
    raw_value = configuration.get(key, default)
    try:
        value = float(raw_value)
    except (TypeError, ValueError):
        LOGGER.warning("Invalid %s=%r; using default %s.", key, raw_value, default)
        return default
    if value < 0:
        LOGGER.warning("Invalid %s=%r; negative values use default %s.", key, raw_value, default)
        return default
    if value == 0 and not allow_zero:
        LOGGER.warning("Invalid %s=%r; zero is not allowed, using default %s.", key, raw_value, default)
        return default
    return value


def _max_attempts_setting(configuration: RuntimeConfiguration) -> int:
    key = "CODING_AGENTS_MODEL_MAX_ATTEMPTS"
    raw_value = configuration.get(key, 3)
    try:
        value = int(raw_value)
    except (TypeError, ValueError):
        LOGGER.warning("Invalid %s=%r; using default 3.", key, raw_value)
        return 3
    if value < 1:
        LOGGER.warning("Invalid %s=%r; using 1.", key, raw_value)
        return 1
    return value


def _is_retryable_provider_error(error: BaseException) -> bool:
    status_code = getattr(error, "status_code", None)
    if status_code in {408, 409, 425, 429, 500, 502, 503, 504}:
        return True
    return error.__class__.__name__ in {
        "APIConnectionError",
        "APITimeoutError",
        "RateLimitError",
        "InternalServerError",
        "ServiceUnavailableError",
    }


def _provider_failure_code(error: BaseException) -> ModelFailureCode:
    status_code = getattr(error, "status_code", None)
    if status_code == 429 or error.__class__.__name__ == "RateLimitError":
        return "rate_limited"
    if status_code == 503 or error.__class__.__name__ == "ServiceUnavailableError":
        return "temporary_unavailable"
    if status_code in {500, 502, 504} or error.__class__.__name__ == "InternalServerError":
        return "server_error"
    return "network_error"
