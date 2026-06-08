# Model Reliability Policy

## Problem

Agent runs can hang when a model request or streamed response stalls without
raising an exception. In that state, the router keeps waiting, no failed
delivery is recorded, and recovery can later mark the run as an incomplete
commit without preserving the original cause.

The reliability layer should support multiple providers, including OpenAI,
Anthropic, Groq, Hugging Face, Ollama, OpenRouter, DeepSeek, and future model
backends.

## Recommendation

Implement a provider-neutral model reliability wrapper around every resolved
chat model. Provider-specific SDK timeout features may still be enabled, but
they should be treated as secondary safeguards rather than the source of truth.

The wrapper should enforce:

- a stream idle timeout based on parsed model chunks or events;
- retry attempts around individual model calls;
- provider-neutral error classification;
- persisted retry and failure metadata for Studio observability.

## Scope

Apply this policy to every model resolved through `ModelResolver`, including
main agents, subagents, translator agents, relation-tool target agents, and any
future provider-backed chat models.

Do not apply automatic retries to non-model tools by default. Filesystem,
terminal, HTTP, approval, and other side-effecting tools need their own
idempotency rules before they can be retried safely.

The reliability wrapper owns model-call retries. Provider SDK retries should be
disabled or kept conservative to avoid hidden retry multiplication.

## Timeout Semantics

Use a stream idle timeout, not a total response timeout.

The timeout starts when the model call begins. It is satisfied by the first
parsed model chunk or event. After that, the timer resets after each subsequent
parsed chunk or event.

This allows long model responses to continue as long as the provider keeps
producing meaningful stream output. It avoids relying on raw socket bytes,
because provider streams may emit keepalives that do not represent model
progress.

Providers that cannot stream should still work, but with degraded reliability.
For non-streaming models, use a total model request timeout and mark the
reliability mode as `non_streaming_timeout`. That fallback prevents indefinite
hangs, but it cannot distinguish a slow valid answer from a stalled request.

The preferred provider adapter behavior is:

```text
streaming supported:
  timeout resets on each parsed model chunk/event

streaming unavailable:
  timeout covers the whole request
  observability marks the mode as degraded
```

## Retry Semantics

Retry the model call, not the whole agent graph.

Retrying the graph can duplicate tool calls, checkpoints, or external side
effects. Retrying the single model request keeps the blast radius small.

Suggested defaults:

```python
@dataclass(frozen=True)
class ModelReliabilityPolicy:
    stream_idle_timeout_s: float = 120
    max_attempts: int = 3
    retry_backoff_initial_s: float = 1
    retry_backoff_max_s: float = 20
```

`max_attempts=3` means the initial attempt plus two retries.

Use exponential backoff with jitter between attempts. Do not retry immediately,
because immediate retries can amplify provider-side overload.

If a retry happens after partial streamed output, the partial output must not be
committed as a final conversation message. Any user-visible partial stream
should carry an `attempt_id`, and Studio should discard or visually supersede
chunks from failed attempts when a later attempt succeeds.

If a model already emitted a tool call and the tool has executed, do not replay
the tool call. The next retry boundary should be the following model call, with
the tool result included in the model input. This keeps retries at model-call
boundaries while avoiding duplicate side effects.

## Error Classification

Normalize provider errors before retry decisions.

Retryable failures:

- stream idle timeout;
- transient network errors;
- provider 429 responses when retryable;
- provider 5xx responses;
- temporary provider unavailable errors.

Non-retryable failures:

- invalid API key;
- permission denied;
- model not found;
- bad request or invalid schema;
- context length exceeded;
- unsupported model parameter.

The reliability wrapper should raise provider-neutral exceptions such as:

```python
class ModelReliabilityError(Exception):
    pass


class RetryableModelError(ModelReliabilityError):
    pass


class NonRetryableModelError(ModelReliabilityError):
    pass


class ModelStreamIdleTimeoutError(RetryableModelError):
    pass
```

Provider adapters should normalize native exceptions into these categories
before the retry policy sees them. For unknown exceptions, default to
non-retryable unless the provider clearly documents them as transient.

Retry classification should be conservative:

- ambiguous auth, permission, model, schema, and context errors are
  non-retryable;
- ambiguous transport errors are retryable only when no request was accepted or
  when the provider/SDK marks the failure retryable;
- stream idle timeouts are retryable until the attempt limit is reached.

## Provider Adapter Contract

Each provider adapter should expose a common capability description:

```python
@dataclass(frozen=True)
class ModelProviderCapabilities:
    provider: str
    model: str
    supports_streaming: bool
    supports_native_chunk_timeout: bool
    supports_native_retries: bool
```

The reliability wrapper should use those capabilities to choose the best
execution mode.

Provider adapters should implement:

- `ainvoke_with_stream_monitoring(...)` when streaming is available;
- `ainvoke_with_request_timeout(...)` as the non-streaming fallback;
- `classify_exception(error)` to return retryable or non-retryable model
  errors;
- optional provider-specific kwargs, such as OpenAI
  `stream_chunk_timeout`, Anthropic stream events, or local-provider request
  timeouts.

For local providers such as Ollama, retry defaults may need to be less
aggressive. Local model cold starts can be slow, and immediate repeated retries
can make resource pressure worse. The provider adapter can override backoff
defaults while keeping the same policy shape.

## Integration Points

`ModelResolver` should resolve the provider model, then wrap it:

```text
ModelResolver
  -> provider chat model
  -> ReliableChatModel(provider_model, policy)
  -> agent factory
```

For OpenAI, also pass the provider-specific streaming options when available:

```python
init_chat_model(
    model=model,
    streaming=True,
    stream_chunk_timeout=policy.stream_idle_timeout_s,
    max_retries=0,
    **kwargs,
)
```

Provider SDK retries should be disabled or kept conservative when the common
wrapper owns retry behavior. This avoids hidden retry multiplication.

The router should call async model execution so stream idle timeouts can be
enforced consistently:

```python
result = await graph.ainvoke(input_payload, config=config)
```

After final retry failure, the router should record a normal failed delivery
with the normalized error message.

Existing sync call sites should be migrated deliberately:

- conversation router: call async graph execution;
- relation tools: use async execution when the tool API supports it, or bridge
  through a controlled async runner;
- legacy sync-only paths: use provider request timeouts and mark reliability as
  degraded until they are migrated.

The wrapper should not require all provider integrations to implement native
stream timeouts. The shared wrapper should enforce the common behavior whenever
the provider exposes a parsed async stream.

## Configuration

Configuration should support global defaults first, then more specific
overrides later.

Recommended initial environment variables:

```text
CODING_AGENTS_MODEL_STREAM_IDLE_TIMEOUT_S=120
CODING_AGENTS_MODEL_MAX_ATTEMPTS=3
CODING_AGENTS_MODEL_RETRY_BACKOFF_INITIAL_S=1
CODING_AGENTS_MODEL_RETRY_BACKOFF_MAX_S=20
```

Future team or agent YAML overrides can map onto the same policy fields. Until
that exists, keep the defaults global to avoid expanding the team schema too
early.

Invalid values should fail closed:

- negative timeout: use the default and log a warning;
- zero timeout: disable idle timeout explicitly;
- `max_attempts < 1`: use `1` and log a warning.

## Observability

Persist retry metadata for each attempt:

```json
{
  "provider": "openai",
  "model": "gpt-5.5",
  "attempt": 2,
  "max_attempts": 3,
  "timeout_s": 120,
  "failure": "stream_idle_timeout"
}
```

Attempt metadata should be written before the attempt starts and updated when
the attempt finishes. That makes in-flight retries visible if the process dies
mid-attempt.

The minimum persisted shape should include:

- run id;
- agent id;
- provider;
- model;
- attempt number;
- max attempts;
- timeout mode;
- timeout seconds;
- started timestamp;
- completed timestamp;
- status: `running`, `retrying`, `success`, `failed`;
- normalized failure code;
- provider error type when safe to expose.

Studio should be able to show states such as:

- `retrying 2/3`;
- `model stream idle timeout after 120s`;
- `failed after 3 attempts`.

Recovery should also record a synthetic failed delivery when it orphans a
pending run:

```text
Run was still pending when the backend restarted; no terminal delivery was recorded.
```

This does not identify the original provider failure, but it prevents silent
unknown/orphaned states.

If recovery orphans a run with a currently running attempt, it should mark that
attempt as failed with `process_interrupted` and then create the synthetic
failed delivery.

## Implementation Order

1. Add provider-neutral reliability errors and policy configuration.
2. Wrap resolved chat models in a `ReliableChatModel`.
3. Enable async streaming execution in the conversation router.
4. Add retry attempt persistence and Studio rendering.
5. Add recovery behavior for orphaned pending runs.
6. Migrate relation-tool and other sync call sites to async or degraded timeout
   handling.
7. Add provider adapters as new providers are introduced.

## Acceptance Criteria

- A stalled model stream fails after the configured idle timeout.
- A model stream that keeps producing parsed chunks is not stopped by total
  elapsed response time.
- Retryable provider failures are retried up to the configured attempt limit.
- Non-retryable provider failures fail immediately.
- Retries happen at the model-call boundary, not by replaying the whole agent
  graph.
- The final failure is recorded as a delivery with a useful error.
- Startup recovery creates a visible failed delivery for orphaned pending runs.
- In-flight attempt metadata survives process interruption.
- Sync-only paths are either migrated to async streaming or explicitly marked
  as degraded with total request timeout behavior.
